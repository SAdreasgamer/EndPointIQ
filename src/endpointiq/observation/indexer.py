"""Project indexer — orchestrates full and incremental indexing.

The indexer is the central coordinator that:
1. Scans all files in a project
2. Runs framework detection
3. Parses each file with tree-sitter
4. Extracts endpoints via the framework plugin
5. Builds dependency and call graphs
6. Populates the NetworkX knowledge graph
7. On file changes, incrementally updates only affected nodes
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from endpointiq.core.config import EndpointIQConfig
from endpointiq.core.events import EventBus
from endpointiq.knowledge.graph import KnowledgeGraph
from endpointiq.models.endpoint import EndpointDefinition
from endpointiq.observation.builders import (
    CallGraphBuilder,
    DependencyGraphBuilder,
    ImportResolver,
)
from endpointiq.observation.parser import ASTParser, detect_language
from endpointiq.observation.plugins.base import (
    DetectionResult,
    PluginManager,
)
from endpointiq.observation.plugins.express_plugin import ExpressPlugin
from endpointiq.observation.watcher import FileChangeEvent, FileFilter

logger = logging.getLogger(__name__)


class ProjectIndexer:
    """Orchestrates full and incremental indexing of a project.

    Usage:
        indexer = ProjectIndexer(config, graph, event_bus)
        stats = indexer.full_index()  # initial scan
        indexer.handle_changes(changes)  # incremental update
    """

    def __init__(
        self,
        config: EndpointIQConfig,
        graph: KnowledgeGraph,
        event_bus: EventBus | None = None,
    ):
        self.config = config
        self.graph = graph
        self.event_bus = event_bus

        # Initialize components
        self.parser = ASTParser(cache_size=config.parser_cache_size)
        self.plugin_manager = PluginManager()
        self.plugin_manager.register(ExpressPlugin())

        self.file_filter = FileFilter(
            ignore_patterns=config.watch_ignore_patterns,
        )

        self.resolver: ImportResolver | None = None
        self.dep_builder: DependencyGraphBuilder | None = None
        self.call_builder = CallGraphBuilder()

        self.detection: DetectionResult | None = None
        self._all_endpoints: list[EndpointDefinition] = []

    @property
    def endpoints(self) -> list[EndpointDefinition]:
        """All discovered endpoints."""
        return list(self._all_endpoints)

    def full_index(self) -> dict:
        """Run a complete index of the project.

        Scans all source files, detects framework, extracts endpoints,
        builds the full knowledge graph.

        Returns:
            Stats dict with counts: files, endpoints, nodes, edges, duration.
        """
        start = time.monotonic()
        project_root = self.config.project_root.resolve()

        logger.info(f"Starting full index of {project_root}")

        # 1. Detect framework
        self.detection = self.plugin_manager.detect_framework(project_root)
        if not self.detection:
            logger.warning("No framework detected")

        # 2. Initialize resolver with project root
        self.resolver = ImportResolver(project_root)
        self.dep_builder = DependencyGraphBuilder(project_root, self.resolver)

        # 3. Scan all source files
        source_files = self._scan_files(project_root)
        logger.info(f"Found {len(source_files)} source files")

        # 4. Clear graph and re-index
        self.graph.clear()
        self._all_endpoints.clear()
        files_indexed = 0

        for file_path in source_files:
            try:
                self._index_file(file_path, project_root)
                files_indexed += 1
            except Exception as e:
                logger.warning(f"Failed to index {file_path}: {e}")

        duration_ms = int((time.monotonic() - start) * 1000)

        stats = {
            "files": files_indexed,
            "endpoints": len(self._all_endpoints),
            "nodes": self.graph.node_count,
            "edges": self.graph.edge_count,
            "framework": self.detection.framework if self.detection else "unknown",
            "confidence": self.detection.confidence if self.detection else 0.0,
            "duration_ms": duration_ms,
        }

        logger.info(
            f"Full index complete: {stats['files']} files, "
            f"{stats['endpoints']} endpoints, "
            f"{stats['nodes']} nodes, {stats['edges']} edges "
            f"in {duration_ms}ms"
        )

        return stats

    def handle_changes(self, changes: list[FileChangeEvent]) -> dict:
        """Incrementally update the graph based on file changes.

        For each changed file:
        1. Prune its old nodes/edges from the graph
        2. Re-parse and re-extract
        3. Upsert new nodes/edges

        Args:
            changes: List of file change events from the watcher.

        Returns:
            Stats dict with counts of what changed.
        """
        start = time.monotonic()
        project_root = self.config.project_root.resolve()

        files_updated = 0
        files_deleted = 0
        endpoints_added = 0
        endpoints_removed = 0

        for change in changes:
            file_path = change.path
            rel_path = self._relative_path(file_path, project_root)

            if change.is_deletion:
                # Prune all nodes from deleted file
                pruned = self.graph.prune_by_provenance(rel_path)
                # Remove endpoints for this file
                before = len(self._all_endpoints)
                self._all_endpoints = [
                    ep for ep in self._all_endpoints if ep.file_path != rel_path
                ]
                endpoints_removed += before - len(self._all_endpoints)
                files_deleted += 1
                logger.debug(f"Pruned {pruned} nodes for deleted file: {rel_path}")
            else:
                # Prune old, then re-index
                self.graph.prune_by_provenance(rel_path)
                self._all_endpoints = [
                    ep for ep in self._all_endpoints if ep.file_path != rel_path
                ]

                try:
                    self._index_file(rel_path, project_root)
                    endpoints_added += len([
                        ep for ep in self._all_endpoints if ep.file_path == rel_path
                    ])
                    files_updated += 1
                except Exception as e:
                    logger.warning(f"Failed to re-index {rel_path}: {e}")

        duration_ms = int((time.monotonic() - start) * 1000)

        stats = {
            "files_updated": files_updated,
            "files_deleted": files_deleted,
            "endpoints_added": endpoints_added,
            "endpoints_removed": endpoints_removed,
            "total_nodes": self.graph.node_count,
            "total_edges": self.graph.edge_count,
            "duration_ms": duration_ms,
        }

        logger.info(f"Incremental update: {stats} in {duration_ms}ms")
        return stats

    def _index_file(self, file_path: str, project_root: Path) -> None:
        """Parse a single file and add its data to the knowledge graph."""
        # Resolve to absolute path for reading
        abs_path = project_root / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not abs_path.exists():
            return

        language = detect_language(str(abs_path))
        if not language:
            return

        source = abs_path.read_bytes()
        rel_path = self._relative_path(str(abs_path), project_root)

        # 1. Parse with tree-sitter
        parse_result = self.parser.parse(source, language, rel_path)

        # 2. Build dependency graph (file nodes + DEPENDS_ON edges)
        if self.dep_builder:
            dep_nodes, dep_edges = self.dep_builder.build_from_file(
                rel_path, parse_result.imports, parse_result.symbols
            )
            self.graph.upsert_subgraph(dep_nodes, dep_edges)

        # 3. Build call graph (CALLS edges)
        call_edges = self.call_builder.build_from_symbols(
            parse_result.symbols, rel_path, source
        )
        self.graph.upsert_edges(call_edges)

        # 4. Extract endpoints via framework plugin
        if self.detection:
            plugin = self.plugin_manager.get_plugin(self.detection.framework)
            if plugin:
                extraction = plugin.extract_endpoints(project_root, rel_path, source)
                if extraction.endpoints:
                    self._all_endpoints.extend(extraction.endpoints)
                    self.graph.upsert_subgraph(extraction.nodes, extraction.edges)

    def _scan_files(self, project_root: Path) -> list[str]:
        """Scan the project directory for all indexable source files."""
        files: list[str] = []
        for path in project_root.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(project_root))
                if self.file_filter.should_include(rel) and detect_language(rel):
                    files.append(rel)
        return sorted(files)

    @staticmethod
    def _relative_path(file_path: str, project_root: Path) -> str:
        """Convert an absolute path to a project-relative path."""
        try:
            return str(Path(file_path).relative_to(project_root))
        except ValueError:
            return file_path

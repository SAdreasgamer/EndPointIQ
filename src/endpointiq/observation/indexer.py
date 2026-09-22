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
from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType
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

        # 5. Post-processing: resolve cross-file references
        cross_file_links = self._resolve_cross_file_references()
        logger.info(f"Resolved {cross_file_links} cross-file references")

        duration_ms = int((time.monotonic() - start) * 1000)

        stats = {
            "files": files_indexed,
            "endpoints": len(self._all_endpoints),
            "nodes": self.graph.node_count,
            "edges": self.graph.edge_count,
            "cross_file_links": cross_file_links,
            "framework": self.detection.framework if self.detection else "unknown",
            "confidence": self.detection.confidence if self.detection else 0.0,
            "duration_ms": duration_ms,
        }

        logger.info(
            f"Full index complete: {stats['files']} files, "
            f"{stats['endpoints']} endpoints, "
            f"{stats['nodes']} nodes, {stats['edges']} edges, "
            f"{cross_file_links} cross-file links "
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

        # 3. Extract endpoints via framework plugin first (so we know route handler nodes)
        handler_nodes: list[GraphNode] = []
        if self.detection:
            plugin = self.plugin_manager.get_plugin(self.detection.framework)
            if plugin:
                extraction = plugin.extract_endpoints(project_root, rel_path, source)
                if extraction.endpoints:
                    self._all_endpoints.extend(extraction.endpoints)
                    self.graph.upsert_subgraph(extraction.nodes, extraction.edges)
                    handler_nodes = [n for n in extraction.nodes if n.type == NodeType.FUNCTION]

        # 4. Build call graph (CALLS edges + placeholder nodes)
        call_nodes, call_edges = self.call_builder.build_calls(
            rel_path, parse_result.symbols, handler_nodes, parse_result.imports, source, language
        )
        self.graph.upsert_subgraph(call_nodes, call_edges)

    def _resolve_cross_file_references(self) -> int:
        """Post-indexing pass: resolve placeholder nodes to real cross-file definitions.

        After all files are indexed, this method:
        1. Builds a global symbol registry (name + file → node_id)
        2. Builds an import map per file (symbol_name → source_file)
        3. For each placeholder node, finds the real definition in the imported file
        4. Rewires edges from placeholder → real definition node

        This handles three call patterns:
        - Direct imports:       await getArticles()        → article.service.ts
        - Dot-method imports:   authController.login       → auth.controller.js
        - Middleware imports:    authMiddleware             → auth.ts

        Returns:
            Number of cross-file links created.
        """
        links_created = 0
        nx = self.graph.graph

        # ── Step 1: Build global symbol registry ──
        # Maps (symbol_name, file_path) → node_id for all real (non-placeholder) nodes
        symbol_registry: dict[tuple[str, str], str] = {}
        for node_id, attrs in nx.nodes(data=True):
            name = attrs.get("qualified_name", "")
            file_path = attrs.get("file_path", "")
            metadata = attrs.get("metadata", {})
            is_placeholder = metadata.get("is_placeholder", False) if isinstance(metadata, dict) else False
            if not is_placeholder and file_path and name:
                symbol_registry[(name, file_path)] = node_id

        # ── Step 2: Build import map per file ──
        # Maps importing_file → {symbol_name: target_file}
        import_maps: dict[str, dict[str, str]] = {}
        for u, v, attrs in nx.edges(data=True):
            if attrs.get("type") != "depends_on":
                continue
            source_data = nx.nodes.get(u, {})
            target_data = nx.nodes.get(v, {})
            source_file = source_data.get("qualified_name", "")
            target_file = target_data.get("qualified_name", "")
            metadata = attrs.get("metadata", {})
            imported_names = metadata.get("names", []) if isinstance(metadata, dict) else []
            is_default = metadata.get("is_default", False) if isinstance(metadata, dict) else False

            if source_file and target_file:
                if source_file not in import_maps:
                    import_maps[source_file] = {}
                for name in imported_names:
                    import_maps[source_file][name] = target_file
                # For default imports, also map the module basename
                # e.g. `import auth from '../auth/auth'` → auth → auth.ts
                if is_default:
                    module_name = metadata.get("module", "")
                    if module_name:
                        basename = module_name.rsplit("/", 1)[-1]
                        import_maps[source_file][basename] = target_file

        # ── Step 3: Resolve placeholders ──
        for node_id, attrs in list(nx.nodes(data=True)):
            metadata = attrs.get("metadata", {})
            is_placeholder = metadata.get("is_placeholder", False) if isinstance(metadata, dict) else False
            if not is_placeholder:
                continue

            placeholder_name = attrs.get("qualified_name", "")
            placeholder_file = attrs.get("file_path", "")

            if not placeholder_name or not placeholder_file:
                continue

            # Strip call parentheses if present: validate(...) -> validate
            clean_name = placeholder_name.split("(")[0].strip()
            if not clean_name:
                continue

            # Determine which symbol to look up in the import map
            if "." in clean_name:
                parts = clean_name.split(".")
                import_lookup = parts[0]  # The imported module/variable name
                method_name = parts[-1]    # The method being called
            else:
                import_lookup = clean_name
                method_name = clean_name

            file_imports = import_maps.get(placeholder_file, {})
            source_file = file_imports.get(import_lookup, "")

            # Transitive re-exports (barrel files e.g. services/index.js -> auth.service.js)
            visited_files: set[str] = set()
            while source_file and source_file in import_maps and import_lookup in import_maps[source_file]:
                if source_file in visited_files:
                    break
                visited_files.add(source_file)
                source_file = import_maps[source_file][import_lookup]

            # If not found via direct import_lookup, check if method_name was imported
            if not source_file:
                source_file = file_imports.get(method_name, "")

            # Find the real definition node in the target or local file
            real_node_id = None

            if not source_file:
                # Could be an intra-file call to a function in the same file
                real_node_id = symbol_registry.get((method_name, placeholder_file))
                if not real_node_id:
                    real_node_id = symbol_registry.get((clean_name, placeholder_file))
            else:
                # Try exact match: (method_name, source_file)
                real_node_id = symbol_registry.get((method_name, source_file))

                # Try qualified name match: (full_name, source_file)
                if not real_node_id:
                    real_node_id = symbol_registry.get((clean_name, source_file))

                # Try matching by just the symbol name across all nodes in the source file
                if not real_node_id:
                    for (name, fpath), nid in symbol_registry.items():
                        if fpath == source_file and name == method_name:
                            real_node_id = nid
                            break

                # If source_file is a barrel/index file, search among files it re-exports
                if not real_node_id and ("index" in source_file or "__init__" in source_file):
                    barrel_targets = set(import_maps.get(source_file, {}).values())
                    for btarget in barrel_targets:
                        real_node_id = symbol_registry.get((method_name, btarget))
                        if not real_node_id:
                            real_node_id = symbol_registry.get((clean_name, btarget))
                        if real_node_id:
                            source_file = btarget
                            break

            if not real_node_id or real_node_id == node_id:
                continue

            # ── Step 4: Rewire edges ──
            for src, _, edge_attrs in list(nx.in_edges(node_id, data=True)):
                edge_type_str = edge_attrs.get("type", "")
                try:
                    edge_type = EdgeType(edge_type_str)
                except ValueError:
                    continue
                self.graph.upsert_edge(GraphEdge(
                    source=src,
                    target=real_node_id,
                    type=edge_type,
                    provenance=edge_attrs.get("provenance", ""),
                    metadata={"cross_file": True},
                ))
                nx.remove_edge(src, node_id)
                links_created += 1
                logger.debug(
                    f"Cross-file link: {placeholder_name} in {placeholder_file} "
                    f"→ real definition in {source_file}"
                )

            # Prune rewired placeholder node if it has no remaining in-edges
            if nx.in_degree(node_id) == 0:
                nx.remove_node(node_id)

        return links_created

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

"""Framework plugin base class and plugin manager.

Defines the interface that all framework plugins must implement,
and the PluginManager that discovers and orchestrates them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from endpointiq.models.endpoint import EndpointDefinition
from endpointiq.models.graph import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """Result of running a framework detection plugin."""

    framework: str  # e.g. "express", "nestjs", "fastapi"
    confidence: float  # 0.0 to 1.0
    version: str = ""  # detected version if available
    language: str = ""  # e.g. "typescript", "javascript", "python"
    entry_files: list[str] = field(default_factory=list)  # main files (app.ts, server.ts)
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Result of extracting endpoints and graph data from a project."""

    endpoints: list[EndpointDefinition] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    middleware: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class IFrameworkPlugin(ABC):
    """Abstract base class that all framework plugins must implement.

    Each plugin is responsible for:
    1. Detecting whether a project uses its framework
    2. Extracting all API endpoints from the codebase
    3. Building framework-specific graph nodes and edges
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Framework name (e.g. 'express', 'nestjs', 'fastapi')."""
        ...

    @property
    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Languages this plugin supports (e.g. ['typescript', 'javascript'])."""
        ...

    @abstractmethod
    def detect(self, project_root: Path) -> DetectionResult:
        """Detect if this framework is used in the project.

        Should check package.json, requirements.txt, pom.xml, etc.
        Returns a DetectionResult with confidence score.
        """
        ...

    @abstractmethod
    def extract_endpoints(
        self, project_root: Path, file_path: str, source: bytes
    ) -> ExtractionResult:
        """Extract endpoints and graph data from a single file.

        Args:
            project_root: Root path of the project.
            file_path: Path to the file being parsed (relative to root).
            source: Raw file content as bytes.

        Returns:
            ExtractionResult with endpoints, nodes, and edges.
        """
        ...


class PluginManager:
    """Discovers and orchestrates framework detection plugins.

    Usage:
        manager = PluginManager()
        manager.register(ExpressPlugin())
        result = manager.detect_framework(Path("/path/to/project"))
    """

    def __init__(self):
        self._plugins: list[IFrameworkPlugin] = []

    def register(self, plugin: IFrameworkPlugin) -> None:
        """Register a framework plugin."""
        self._plugins.append(plugin)
        logger.info(f"Registered plugin: {plugin.name}")

    def detect_framework(self, project_root: Path) -> DetectionResult | None:
        """Run all plugins and return the highest-confidence detection.

        Returns None if no framework is detected with confidence > 0.5.
        """
        best: DetectionResult | None = None

        for plugin in self._plugins:
            try:
                result = plugin.detect(project_root)
                logger.debug(
                    f"Plugin '{plugin.name}' detected with confidence {result.confidence}"
                )
                if result.confidence > 0.5 and (
                    best is None or result.confidence > best.confidence
                ):
                    best = result
            except Exception as e:
                logger.warning(f"Plugin '{plugin.name}' detection failed: {e}")

        if best:
            logger.info(
                f"Detected framework: {best.framework} "
                f"(confidence: {best.confidence}, version: {best.version})"
            )
        return best

    def get_plugin(self, framework_name: str) -> IFrameworkPlugin | None:
        """Get a plugin by framework name."""
        for plugin in self._plugins:
            if plugin.name == framework_name:
                return plugin
        return None

    @property
    def plugins(self) -> list[IFrameworkPlugin]:
        """All registered plugins."""
        return list(self._plugins)

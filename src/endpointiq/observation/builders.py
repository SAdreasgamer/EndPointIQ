"""Dependency and call graph builders.

Analyzes import statements and call expressions to build
DEPENDS_ON and CALLS edges in the knowledge graph.

Also classifies code entities by role (controller, service,
repository) based on naming conventions and decorators.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from endpointiq.observation.parser import Import, Symbol

logger = logging.getLogger(__name__)


def _make_id(kind: str, name: str, file_path: str) -> str:
    """Generate a deterministic node ID."""
    raw = f"{kind}:{name}:{file_path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Role Classification ──────────────────────────────

# Naming patterns for classifying code entities
ROLE_PATTERNS: dict[NodeType, list[re.Pattern]] = {
    NodeType.CONTROLLER: [
        re.compile(r"(?i)controller"),
        re.compile(r"(?i)handler"),
        re.compile(r"(?i)route[rs]?$"),
    ],
    NodeType.SERVICE: [
        re.compile(r"(?i)service"),
        re.compile(r"(?i)usecase"),
        re.compile(r"(?i)manager"),
    ],
    NodeType.REPOSITORY: [
        re.compile(r"(?i)repositor[y|ies]"),
        re.compile(r"(?i)dao"),
        re.compile(r"(?i)model"),
        re.compile(r"(?i)store"),
    ],
    NodeType.MIDDLEWARE: [
        re.compile(r"(?i)middleware"),
        re.compile(r"(?i)guard"),
        re.compile(r"(?i)interceptor"),
    ],
    NodeType.VALIDATOR: [
        re.compile(r"(?i)validat(?:or|ion|e)"),
        re.compile(r"(?i)schema"),
        re.compile(r"(?i)dto"),
    ],
    NodeType.CONFIG: [
        re.compile(r"(?i)config"),
        re.compile(r"(?i)settings"),
        re.compile(r"(?i)env"),
    ],
    NodeType.ENTITY: [
        re.compile(r"(?i)entity"),
        re.compile(r"(?i)interface"),
        re.compile(r"(?i)type[s]?$"),
    ],
}


def classify_role(name: str, decorators: list[str] | None = None) -> NodeType:
    """Classify a code entity by its likely architectural role.

    Uses naming conventions and decorators to determine if something
    is a controller, service, repository, etc.

    Args:
        name: The class/function name (e.g. "UserController", "AuthService").
        decorators: Optional list of decorators applied to the entity.

    Returns:
        The classified NodeType, defaulting to CLASS if no match.
    """
    # Check decorators first (most reliable)
    if decorators:
        decorator_str = " ".join(decorators).lower()
        if "controller" in decorator_str:
            return NodeType.CONTROLLER
        if "injectable" in decorator_str or "service" in decorator_str:
            return NodeType.SERVICE
        if "entity" in decorator_str or "schema" in decorator_str:
            return NodeType.ENTITY
        if "middleware" in decorator_str or "guard" in decorator_str:
            return NodeType.MIDDLEWARE

    # Fall back to naming patterns
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(name):
                return role

    return NodeType.CLASS


# ── Import Resolution ─────────────────────────────────


class ImportResolver:
    """Resolves import paths to actual file paths.

    Handles:
    - Relative imports (./foo, ../bar)
    - TypeScript path aliases from tsconfig.json
    - Barrel exports (index.ts)
    - Extension resolution (.ts, .js, /index.ts)
    """

    def __init__(self, project_root: Path, tsconfig_paths: dict[str, list[str]] | None = None):
        self.project_root = project_root
        self.tsconfig_paths = tsconfig_paths or {}
        self._ts_aliases = self._load_ts_aliases()

    def _load_ts_aliases(self) -> dict[str, str]:
        """Load TypeScript path aliases from tsconfig.json."""
        aliases: dict[str, str] = {}
        tsconfig_path = self.project_root / "tsconfig.json"
        if not tsconfig_path.exists():
            return aliases

        try:
            config = json.loads(tsconfig_path.read_text())
            compiler_opts = config.get("compilerOptions", {})
            base_url = compiler_opts.get("baseUrl", ".")
            paths = compiler_opts.get("paths", {})

            for alias_pattern, targets in paths.items():
                # Convert "@/*" → "@/" prefix
                alias_prefix = alias_pattern.replace("*", "")
                if targets:
                    target_prefix = targets[0].replace("*", "")
                    resolved = str(self.project_root / base_url / target_prefix)
                    aliases[alias_prefix] = resolved
        except (json.JSONDecodeError, OSError):
            pass

        return aliases

    def resolve(self, import_module: str, from_file: str) -> str | None:
        """Resolve an import module path to an actual file path.

        Args:
            import_module: The import string (e.g. "./services/UserService").
            from_file: The file containing the import (for relative resolution).

        Returns:
            Resolved absolute file path, or None if unresolvable.
        """
        if not import_module:
            return None

        # Skip node_modules / external packages
        if not import_module.startswith(".") and not any(
            import_module.startswith(alias) for alias in self._ts_aliases
        ):
            return None  # External package — skip

        # Resolve TypeScript aliases
        for alias_prefix, resolved_prefix in self._ts_aliases.items():
            if import_module.startswith(alias_prefix):
                remainder = import_module[len(alias_prefix):]
                resolved_base = Path(resolved_prefix) / remainder
                return self._try_extensions(resolved_base)

        # Resolve relative imports
        from_dir = Path(from_file).parent
        if not from_dir.is_absolute():
            from_dir = self.project_root / from_dir

        target = from_dir / import_module
        return self._try_extensions(target)

    def _try_extensions(self, base_path: Path) -> str | None:
        """Try common file extensions and index files."""
        candidates = [
            base_path,
            base_path.with_suffix(".ts"),
            base_path.with_suffix(".tsx"),
            base_path.with_suffix(".js"),
            base_path.with_suffix(".jsx"),
            base_path / "index.ts",
            base_path / "index.js",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        return None


# ── Dependency Graph Builder ──────────────────────────


class DependencyGraphBuilder:
    """Builds DEPENDS_ON and IMPORTS edges from import statements.

    Given parse results for multiple files, creates edges showing
    which files depend on which other files.
    """

    def __init__(self, project_root: Path, resolver: ImportResolver | None = None):
        self.project_root = project_root
        self.resolver = resolver or ImportResolver(project_root)

    def build_from_file(
        self,
        file_path: str,
        imports: list[Import],
        symbols: list[Symbol],
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Build graph nodes and dependency edges for a single file.

        Creates:
        - A FILE node for this file
        - CLASS/FUNCTION nodes for each symbol
        - DEPENDS_ON edges for each resolved import
        - BELONGS_TO edges connecting symbols to their file

        Args:
            file_path: Path to the source file.
            imports: Import statements extracted by the parser.
            symbols: Symbols (classes, functions) extracted by the parser.

        Returns:
            Tuple of (nodes, edges).
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # Create file node
        file_node_id = _make_id("file", file_path, file_path)
        file_node = GraphNode(
            id=file_node_id,
            type=NodeType.FILE,
            qualified_name=file_path,
            file_path=file_path,
            line_start=1,
            line_end=1,
            provenance=file_path,
        )
        nodes.append(file_node)

        # Create symbol nodes with role classification
        for sym in symbols:
            role = classify_role(sym.name, sym.decorators)
            node_id = _make_id(sym.kind, sym.qualified_name, file_path)
            node = GraphNode(
                id=node_id,
                type=role,
                qualified_name=sym.qualified_name,
                file_path=file_path,
                line_start=sym.line_start,
                line_end=sym.line_end,
                provenance=file_path,
                metadata={
                    "kind": sym.kind,
                    "decorators": sym.decorators,
                    "parameters": sym.parameters,
                },
            )
            nodes.append(node)

            # BELONGS_TO edge: symbol → file
            edges.append(GraphEdge(
                source=node_id,
                target=file_node_id,
                type=EdgeType.BELONGS_TO,
                provenance=file_path,
            ))

        # Create DEPENDS_ON edges from imports
        for imp in imports:
            resolved = self.resolver.resolve(imp.module, file_path)
            if resolved:
                target_file_id = _make_id("file", resolved, resolved)
                edges.append(GraphEdge(
                    source=file_node_id,
                    target=target_file_id,
                    type=EdgeType.DEPENDS_ON,
                    provenance=file_path,
                    metadata={"module": imp.module},
                ))

        return nodes, edges


# ── Call Graph Builder ────────────────────────────────


class CallGraphBuilder:
    """Builds CALLS edges by analyzing function call expressions.

    Detects patterns like:
    - this.userService.create(...)  → CALLS edge from method to service method
    - await repository.save(...)   → CALLS edge from service to repository

    Uses constructor parameter analysis to resolve `this.xxx` references.
    """

    def build_from_symbols(
        self,
        symbols: list[Symbol],
        file_path: str,
        source: bytes,
    ) -> list[GraphEdge]:
        """Build CALLS edges from method bodies within a file.

        Analyzes each method/function body looking for call expressions
        that reference other symbols (typically via `this.service.method()`).

        Args:
            symbols: All symbols extracted from the file.
            file_path: Path to the source file.
            source: Raw source code for text extraction.

        Returns:
            List of CALLS edges.
        """
        edges: list[GraphEdge] = []
        lines = source.decode("utf-8", errors="replace").split("\n")

        # Build a map of known symbol names in this file
        symbol_map: dict[str, Symbol] = {}
        for sym in symbols:
            symbol_map[sym.name] = sym
            symbol_map[sym.qualified_name] = sym

        # For each method, scan its body for call patterns
        for sym in symbols:
            if sym.kind not in ("method", "function"):
                continue

            # Extract method body lines
            body_start = max(0, sym.line_start - 1)
            body_end = min(len(lines), sym.line_end)
            body = "\n".join(lines[body_start:body_end])

            # Find call patterns: this.xxx.yyy() or xxx.yyy()
            call_pattern = re.compile(
                r'(?:this\.)?(\w+)\.(\w+)\s*\('
            )
            for match in call_pattern.finditer(body):
                service_name = match.group(1)
                method_name = match.group(2)
                target_qualified = f"{service_name}.{method_name}"

                # Create a CALLS edge
                source_id = _make_id(sym.kind, sym.qualified_name, file_path)
                target_id = _make_id("method", target_qualified, file_path)

                edges.append(GraphEdge(
                    source=source_id,
                    target=target_id,
                    type=EdgeType.CALLS,
                    provenance=file_path,
                    metadata={
                        "caller": sym.qualified_name,
                        "callee": target_qualified,
                    },
                ))

        return edges

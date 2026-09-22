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
            Resolved project-relative file path, or None if unresolvable.
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
                return self._normalize_path(self._try_extensions(resolved_base))

        # Resolve relative imports
        from_dir = Path(from_file).parent
        if not from_dir.is_absolute():
            from_dir = self.project_root / from_dir

        # Handle Python relative imports like '.service' or '..service'
        rel_module = import_module
        if rel_module.startswith(".") and not rel_module.startswith("./") and not rel_module.startswith("../"):
            dots = len(rel_module) - len(rel_module.lstrip("."))
            rest = rel_module[dots:].replace(".", "/")
            prefix = "../" * (dots - 1) if dots > 1 else "./"
            rel_module = prefix + rest

        target = from_dir / rel_module
        return self._normalize_path(self._try_extensions(target))

    def _normalize_path(self, file_path: str | None) -> str | None:
        """Normalize a resolved file path to be project-relative.

        Removes '../' segments and makes the path relative to project_root
        so that node IDs match between the file node and the DEPENDS_ON target.
        """
        if not file_path:
            return None
        try:
            abs_path = Path(file_path).resolve()
            return str(abs_path.relative_to(self.project_root.resolve()))
        except ValueError:
            # File is outside project root — return as-is
            return str(Path(file_path).resolve())

    def _try_extensions(self, base_path: Path) -> str | None:
        """Try common file extensions and index files."""
        s = str(base_path)
        candidates = [
            base_path,
            Path(s + ".ts"),
            Path(s + ".tsx"),
            Path(s + ".js"),
            Path(s + ".jsx"),
            Path(s + ".py"),
            base_path / "index.ts",
            base_path / "index.js",
            base_path / "__init__.py",
            base_path.with_suffix(".ts"),
            base_path.with_suffix(".js"),
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
                    metadata={
                        "module": imp.module,
                        "names": imp.names,
                        "is_default": imp.is_default,
                    },
                ))

        return nodes, edges


# ── Call Graph Builder ────────────────────────────────


class CallGraphBuilder:
    """Builds CALLS edges by analyzing function call expressions.

    Detects patterns like:
    - this.userService.create(...) → CALLS edge from method to service method
    - authService.loginUserWithEmailAndPassword(...) → CALLS edge to imported service
    - getArticles(...) → CALLS edge to imported function
    - await repository.save(...) → CALLS edge from service to repository
    """

    def build_calls(
        self,
        file_path: str,
        symbols: list[Symbol],
        handler_nodes: list[GraphNode],
        imports: list[Import],
        source: bytes,
        language: str | None = None,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Build CALLS edges and placeholder callee nodes.

        Analyzes calls inside:
        - Symbol functions/methods (from AST)
        - Handler functions from plugins (e.g. express route handlers)

        Returns:
            Tuple of (placeholder_nodes, call_edges).
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # 1. Build caller list
        callers: list[dict] = []
        seen_ids: set[str] = set()
        for sym in symbols:
            if sym.kind in ("function", "method"):
                cid = _make_id(sym.kind, sym.qualified_name, file_path)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    callers.append({
                        "id": cid,
                        "name": sym.qualified_name,
                        "kind": sym.kind,
                        "line_start": sym.line_start,
                        "line_end": sym.line_end,
                    })

        for hnode in handler_nodes:
            if hnode.type == NodeType.FUNCTION:
                if hnode.id not in seen_ids:
                    seen_ids.add(hnode.id)
                    callers.append({
                        "id": hnode.id,
                        "name": hnode.qualified_name,
                        "kind": "function",
                        "line_start": hnode.line_start,
                        "line_end": hnode.line_end,
                    })

        if not callers:
            return nodes, edges

        # 2. Collect imported symbols and local symbols
        imported_symbols: set[str] = set()
        for imp in imports:
            for name in imp.names:
                imported_symbols.add(name)
            if imp.alias:
                imported_symbols.add(imp.alias)
            if imp.is_default and imp.module:
                imported_symbols.add(imp.module.rsplit("/", 1)[-1])

        file_symbols = {s.name: s for s in symbols}
        for s in symbols:
            file_symbols[s.qualified_name] = s

        # 3. Extract calls using tree-sitter AST if available, fallback to regex
        calls: list[tuple[str, int]] = []
        if language:
            try:
                from tree_sitter_languages import get_parser
                ts_parser = get_parser(language)
                tree = ts_parser.parse(source)

                def walk(n):
                    if language in ("typescript", "tsx", "javascript"):
                        if n.type == "call_expression":
                            func = n.child_by_field_name("function")
                            if func:
                                if func.type == "identifier":
                                    calls.append((func.text.decode("utf-8") if isinstance(func.text, bytes) else func.text, n.start_point[0] + 1))
                                elif func.type == "member_expression":
                                    obj = func.child_by_field_name("object")
                                    prop = func.child_by_field_name("property")
                                    if obj and prop:
                                        otext = obj.text.decode("utf-8") if isinstance(obj.text, bytes) else obj.text
                                        ptext = prop.text.decode("utf-8") if isinstance(prop.text, bytes) else prop.text
                                        calls.append((f"{otext}.{ptext}", n.start_point[0] + 1))
                    elif language == "python":
                        if n.type == "call":
                            func = n.child_by_field_name("function")
                            if func:
                                if func.type == "identifier":
                                    calls.append((func.text.decode("utf-8") if isinstance(func.text, bytes) else func.text, n.start_point[0] + 1))
                                elif func.type == "attribute":
                                    obj = func.child_by_field_name("object")
                                    attr = func.child_by_field_name("attribute")
                                    if obj and attr:
                                        otext = obj.text.decode("utf-8") if isinstance(obj.text, bytes) else obj.text
                                        atext = attr.text.decode("utf-8") if isinstance(attr.text, bytes) else attr.text
                                        calls.append((f"{otext}.{atext}", n.start_point[0] + 1))
                    for c in n.children:
                        walk(c)

                walk(tree.root_node)
            except Exception:
                pass

        if not calls:
            lines = source.decode("utf-8", errors="replace").split("\n")
            dot_pattern = re.compile(r'(?:this\.)?([a-zA-Z_$][\w$]*)\.([a-zA-Z_$][\w$]*)\s*\(')
            for idx, line in enumerate(lines, start=1):
                for m in dot_pattern.finditer(line):
                    calls.append((f"{m.group(1)}.{m.group(2)}", idx))

        ignore = {
            "require", "import", "Router", "express", "catchAsync", "Number", "String",
            "Boolean", "console", "res", "req", "next", "status", "json", "send",
            "Promise", "Object", "Array", "Math", "Date", "Error", "print", "len",
            "range", "isinstance", "super", "type", "str", "int", "dict", "list",
            "set", "tuple", "any", "all", "min", "max",
        }

        seen_edges: set[tuple[str, str]] = set()

        for callee, line in calls:
            base = callee.lstrip("this.").split(".")[0]
            if base in ignore:
                continue

            # Check if this call is relevant: imported symbol, file symbol, or this.xxx
            is_relevant = (
                base in imported_symbols
                or base in file_symbols
                or callee.startswith("this.")
            )
            if not is_relevant:
                continue

            # Find enclosing caller
            enclosing = [c for c in callers if c["line_start"] <= line <= c["line_end"]]
            if not enclosing:
                continue
            tightest = min(enclosing, key=lambda c: c["line_end"] - c["line_start"])
            source_id = tightest["id"]

            # If callee is defined in the same file:
            if callee in file_symbols:
                target_sym = file_symbols[callee]
                target_id = _make_id(target_sym.kind, target_sym.qualified_name, file_path)
                edge_key = (source_id, target_id)
                if edge_key not in seen_edges and source_id != target_id:
                    seen_edges.add(edge_key)
                    edges.append(GraphEdge(
                        source=source_id,
                        target=target_id,
                        type=EdgeType.CALLS,
                        provenance=file_path,
                        metadata={"caller": tightest["name"], "callee": callee},
                    ))
            else:
                # Imported or external call: create placeholder node
                target_id = _make_id("function", callee, file_path)
                edge_key = (source_id, target_id)
                if edge_key not in seen_edges and source_id != target_id:
                    seen_edges.add(edge_key)
                    callee_node = GraphNode(
                        id=target_id,
                        type=NodeType.FUNCTION,
                        qualified_name=callee,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                        provenance=file_path,
                        metadata={"is_placeholder": True},
                    )
                    nodes.append(callee_node)
                    edges.append(GraphEdge(
                        source=source_id,
                        target=target_id,
                        type=EdgeType.CALLS,
                        provenance=file_path,
                        metadata={"caller": tightest["name"], "callee": callee},
                    ))

        return nodes, edges

    def build_from_symbols(
        self,
        symbols: list[Symbol],
        file_path: str,
        source: bytes,
    ) -> list[GraphEdge]:
        """Backward-compatible helper that returns edges from symbols."""
        from endpointiq.observation.parser import detect_language
        lang = detect_language(file_path)
        _, edges = self.build_calls(file_path, symbols, [], [], source, lang)
        return edges

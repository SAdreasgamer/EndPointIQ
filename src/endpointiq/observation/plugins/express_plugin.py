"""Express.js framework detection and endpoint extraction plugin.

Detects Express projects by checking package.json for the 'express' dependency.
Extracts endpoints by parsing route definitions using tree-sitter AST queries:
  - app.get("/path", handler)
  - router.post("/path", handler)
  - app.use("/prefix", router)  (sub-router mounting)
  - app.use(middleware)          (global middleware)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from tree_sitter_languages import get_parser

from endpointiq.models.endpoint import EndpointDefinition, HttpMethod
from endpointiq.models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from endpointiq.observation.plugins.base import (
    DetectionResult,
    ExtractionResult,
    IFrameworkPlugin,
)

logger = logging.getLogger(__name__)

# HTTP methods that Express supports for routing
EXPRESS_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "all"}

# Common Express variable names for app and router
EXPRESS_APP_NAMES = {"app", "server", "api"}
EXPRESS_ROUTER_NAMES = {"router", "route", "routes"}
EXPRESS_RECEIVER_NAMES = EXPRESS_APP_NAMES | EXPRESS_ROUTER_NAMES


def _make_node_id(kind: str, name: str, file_path: str) -> str:
    """Generate a deterministic node ID."""
    raw = f"{kind}:{name}:{file_path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ExpressPlugin(IFrameworkPlugin):
    """Plugin for detecting and extracting endpoints from Express.js projects."""

    @property
    def name(self) -> str:
        return "express"

    @property
    def supported_languages(self) -> list[str]:
        return ["typescript", "javascript"]

    def detect(self, project_root: Path) -> DetectionResult:
        """Detect Express.js by checking package.json dependencies."""
        pkg_path = project_root / "package.json"
        if not pkg_path.exists():
            return DetectionResult(framework="express", confidence=0.0)

        try:
            pkg = json.loads(pkg_path.read_text())
        except (json.JSONDecodeError, OSError):
            return DetectionResult(framework="express", confidence=0.0)

        # Check dependencies and devDependencies
        deps = pkg.get("dependencies", {})
        dev_deps = pkg.get("devDependencies", {})
        all_deps = {**deps, **dev_deps}

        if "express" not in all_deps:
            return DetectionResult(framework="express", confidence=0.0)

        version = all_deps.get("express", "unknown")

        # Determine language
        language = "javascript"
        if "typescript" in all_deps or (project_root / "tsconfig.json").exists():
            language = "typescript"

        # Find entry files
        entry_files: list[str] = []
        main = pkg.get("main", "")
        if main:
            entry_files.append(main)
        for candidate in ["app.ts", "app.js", "server.ts", "server.js", "index.ts", "index.js",
                          "src/app.ts", "src/app.js", "src/server.ts", "src/server.js",
                          "src/index.ts", "src/index.js"]:
            if (project_root / candidate).exists():
                entry_files.append(candidate)

        return DetectionResult(
            framework="express",
            confidence=0.95,
            version=version,
            language=language,
            entry_files=entry_files,
            metadata={"has_typescript": language == "typescript"},
        )

    def extract_endpoints(
        self, project_root: Path, file_path: str, source: bytes
    ) -> ExtractionResult:
        """Extract Express endpoints from a source file using tree-sitter.

        Parses the AST looking for patterns like:
        - app.get("/path", handler)
        - router.post("/path", middleware, handler)
        - app.use("/prefix", routerVar)
        - app.use(middlewareFunc)
        """
        # Determine language from extension
        ext = Path(file_path).suffix.lower()
        if ext in (".ts", ".tsx"):
            lang = "typescript"
        elif ext in (".js", ".jsx", ".mjs", ".cjs"):
            lang = "javascript"
        else:
            return ExtractionResult()

        parser = get_parser(lang)
        tree = parser.parse(source)
        root = tree.root_node

        endpoints: list[EndpointDefinition] = []
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        middleware_list: list[str] = []

        # Walk the AST looking for call expressions
        self._walk_for_routes(
            root, file_path, project_root, endpoints, nodes, edges, middleware_list
        )

        return ExtractionResult(
            endpoints=endpoints,
            nodes=nodes,
            edges=edges,
            middleware=middleware_list,
        )

    def _walk_for_routes(
        self,
        node,
        file_path: str,
        project_root: Path,
        endpoints: list[EndpointDefinition],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        middleware_list: list[str],
        router_prefix: str = "",
    ) -> None:
        """Recursively walk AST to find route definitions."""
        if node.type == "call_expression":
            self._try_extract_route(
                node, file_path, project_root,
                endpoints, nodes, edges, middleware_list, router_prefix
            )

        # Recurse into children
        for child in node.children:
            self._walk_for_routes(
                child, file_path, project_root,
                endpoints, nodes, edges, middleware_list, router_prefix
            )

    def _try_extract_route(
        self,
        node,
        file_path: str,
        project_root: Path,
        endpoints: list[EndpointDefinition],
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        middleware_list: list[str],
        router_prefix: str,
    ) -> None:
        """Try to extract a route from a call_expression node.

        Matches patterns like:
        - app.get("/users", handler)
        - router.post("/users", validate, handler)
        - app.use("/api", router)
        - app.use(cors())
        """
        # Get the function being called (e.g. app.get, router.post)
        func = node.child_by_field_name("function")
        if not func or func.type != "member_expression":
            return

        # Extract object and property
        obj = func.child_by_field_name("object")
        prop = func.child_by_field_name("property")
        if not obj or not prop:
            return

        obj_name = self._node_text(obj)
        method_name = self._node_text(prop)

        if not obj_name or not method_name:
            return

        # Check if this is a recognized Express receiver
        base_name = obj_name.split(".")[-1] if "." in obj_name else obj_name
        if base_name.lower() not in EXPRESS_RECEIVER_NAMES:
            return

        # Get arguments
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return
        args = [
            c for c in args_node.children
            if c.type not in ("(", ")", ",")
        ]

        # Handle app.use() — middleware or sub-router mounting
        if method_name == "use":
            self._handle_use(
                args, file_path, nodes, edges, middleware_list, router_prefix
            )
            return

        # Handle route definitions: app.get("/path", ...handlers)
        if method_name.lower() not in EXPRESS_HTTP_METHODS:
            return

        if len(args) < 2:
            return

        # First arg should be the path string
        path_arg = args[0]
        path = self._extract_string(path_arg)
        if not path:
            return

        full_path = router_prefix + path if router_prefix else path

        # Remaining args are middleware + handler (last one is the handler)
        handler_args = args[1:]
        handler_name = self._node_text(handler_args[-1]) if handler_args else "anonymous"
        mw_names = [self._node_text(a) for a in handler_args[:-1]]
        mw_names = [m for m in mw_names if m]

        # Map method name
        http_method = HttpMethod.GET
        method_upper = method_name.upper()
        if method_upper in HttpMethod.__members__:
            http_method = HttpMethod(method_upper)

        # Create endpoint
        ep = EndpointDefinition(
            method=http_method,
            path=full_path,
            handler=handler_name,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            framework="express",
            middleware=mw_names,
        )
        endpoints.append(ep)

        # Create graph nodes and edges
        ep_node_id = _make_node_id("endpoint", ep.display_name, file_path)
        ep_node = GraphNode(
            id=ep_node_id,
            type=NodeType.ENDPOINT,
            qualified_name=ep.display_name,
            file_path=file_path,
            line_start=ep.line_start,
            line_end=ep.line_end,
            provenance=file_path,
            metadata={"method": str(http_method), "path": full_path},
        )
        nodes.append(ep_node)

        # Handler node
        handler_node_id = _make_node_id("function", handler_name, file_path)
        handler_node = GraphNode(
            id=handler_node_id,
            type=NodeType.FUNCTION,
            qualified_name=handler_name,
            file_path=file_path,
            line_start=ep.line_start,
            line_end=ep.line_end,
            provenance=file_path,
        )
        nodes.append(handler_node)
        edges.append(GraphEdge(
            source=ep_node_id,
            target=handler_node_id,
            type=EdgeType.CALLS,
            provenance=file_path,
        ))

        # Middleware nodes
        for mw in mw_names:
            mw_node_id = _make_node_id("middleware", mw, file_path)
            mw_node = GraphNode(
                id=mw_node_id,
                type=NodeType.MIDDLEWARE,
                qualified_name=mw,
                file_path=file_path,
                line_start=ep.line_start,
                line_end=ep.line_end,
                provenance=file_path,
            )
            nodes.append(mw_node)
            edges.append(GraphEdge(
                source=ep_node_id,
                target=mw_node_id,
                type=EdgeType.SECURED_BY,
                provenance=file_path,
            ))

    def _handle_use(
        self,
        args: list,
        file_path: str,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        middleware_list: list[str],
        router_prefix: str,
    ) -> None:
        """Handle app.use() calls — either global middleware or sub-router mounts."""
        if not args:
            return

        # app.use("/prefix", router) — sub-router mounting
        if len(args) >= 2:
            path = self._extract_string(args[0])
            if path:
                # This is a sub-router mount
                router_name = self._node_text(args[-1])
                if router_name:
                    mount_id = _make_node_id("mount", path, file_path)
                    mount_node = GraphNode(
                        id=mount_id,
                        type=NodeType.MODULE,
                        qualified_name=f"mount:{path}→{router_name}",
                        file_path=file_path,
                        line_start=args[0].start_point[0] + 1,
                        line_end=args[-1].end_point[0] + 1,
                        provenance=file_path,
                        metadata={"prefix": path, "router": router_name},
                    )
                    nodes.append(mount_node)
                return

        # app.use(middleware) — global middleware
        mw_name = self._node_text(args[0])
        if mw_name:
            # Strip function calls like cors() → cors
            clean_name = mw_name.split("(")[0].strip()
            middleware_list.append(clean_name)
            mw_node_id = _make_node_id("middleware", clean_name, file_path)
            mw_node = GraphNode(
                id=mw_node_id,
                type=NodeType.MIDDLEWARE,
                qualified_name=clean_name,
                file_path=file_path,
                line_start=args[0].start_point[0] + 1,
                line_end=args[0].end_point[0] + 1,
                provenance=file_path,
            )
            nodes.append(mw_node)

    @staticmethod
    def _node_text(node) -> str:
        """Extract text from a tree-sitter node."""
        if node is None:
            return ""
        text = node.text
        if isinstance(text, bytes):
            return text.decode("utf-8").strip()
        return str(text).strip()

    @staticmethod
    def _extract_string(node) -> str | None:
        """Extract a string literal value from a tree-sitter node.

        Handles both 'single' and "double" quoted strings,
        and template literals.
        """
        if node is None:
            return None
        raw = node.text
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        text: str = str(raw).strip()
        # Remove quotes
        if (text.startswith("'") and text.endswith("'")) or \
           (text.startswith('"') and text.endswith('"')):
            return text[1:-1]
        if text.startswith("`") and text.endswith("`"):
            return text[1:-1]
        return None

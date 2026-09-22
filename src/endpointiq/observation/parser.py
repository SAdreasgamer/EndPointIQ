"""Multi-language AST parser using tree-sitter.

Parses source code files into syntax trees, extracts symbols
(classes, functions, methods, imports), and supports incremental
parsing for fast updates on file changes.

Key features:
- Incremental parsing: only re-parses changed nodes
- Error-tolerant: parses broken/incomplete code
- Multi-language: TypeScript, JavaScript, Python, Java, Go, C#
- Symbol extraction: classes, functions, methods, imports, exports
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter_languages import get_parser

logger = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────


@dataclass
class Symbol:
    """A code symbol extracted from the AST (class, function, method, etc.)."""

    name: str
    qualified_name: str  # e.g. "UserController.create"
    kind: str  # "class" | "function" | "method" | "variable"
    file_path: str
    line_start: int
    line_end: int
    decorators: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    parent: str | None = None  # parent class name, if method
    source_code: str = ""


@dataclass
class Import:
    """An import statement extracted from the AST."""

    module: str  # what is being imported from
    names: list[str]  # what is being imported
    is_default: bool = False
    is_namespace: bool = False  # import * as X
    alias: str | None = None
    line: int = 0


@dataclass
class Export:
    """An export statement extracted from the AST."""

    name: str
    is_default: bool = False
    line: int = 0


@dataclass
class ParseError:
    """A parse error found in the source code."""

    message: str
    line: int
    column: int


@dataclass
class ParseResult:
    """Complete result of parsing a source file."""

    tree: object  # tree-sitter Tree object
    language: str
    file_path: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


# ── Language Detection ────────────────────────────────


LANGUAGE_MAP: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
    ".java": "java",
    ".go": "go",
    ".cs": "c_sharp",
}


def detect_language(file_path: str) -> str | None:
    """Detect the programming language from a file extension."""
    suffix = Path(file_path).suffix.lower()
    return LANGUAGE_MAP.get(suffix)


# ── Symbol Extractor ──────────────────────────────────


class SymbolExtractor:
    """Extracts symbols (classes, functions, imports) from a tree-sitter AST.

    Language-specific extraction logic for TypeScript, JavaScript, and Python.
    """

    def __init__(self, language: str, file_path: str = ""):
        self.language = language
        self.file_path = file_path

    def extract(self, root_node) -> tuple[list[Symbol], list[Import], list[Export]]:
        """Extract all symbols, imports, and exports from the AST root node."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        exports: list[Export] = []

        self._walk(root_node, symbols, imports, exports, parent_class=None)
        return symbols, imports, exports

    def _walk(self, node, symbols, imports, exports, parent_class=None):
        """Recursively walk the AST and extract symbols."""
        # TypeScript / JavaScript
        if self.language in ("typescript", "tsx", "javascript"):
            self._extract_ts_js(node, symbols, imports, exports, parent_class)
        # Python
        elif self.language == "python":
            self._extract_python(node, symbols, imports, exports, parent_class)
        # Java
        elif self.language == "java":
            self._extract_java(node, symbols, imports, exports, parent_class)

    def _extract_ts_js(self, node, symbols, imports, exports, parent_class):
        """Extract symbols from TypeScript/JavaScript AST."""
        node_type = node.type

        # Class declarations
        if node_type == "class_declaration":
            name = self._get_child_text(node, "type_identifier") or self._get_child_text(node, "identifier")
            if name:
                decorators = self._get_decorators_ts(node)
                sym = Symbol(
                    name=name,
                    qualified_name=name,
                    kind="class",
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    decorators=decorators,
                )
                symbols.append(sym)
                # Walk children with class context
                for child in node.children:
                    self._walk(child, symbols, imports, exports, parent_class=name)
                return

        # Function declarations
        if node_type in ("function_declaration", "arrow_function", "method_definition"):
            name = self._get_child_text(node, "identifier") or self._get_child_text(node, "property_identifier")
            if name:
                qualified = f"{parent_class}.{name}" if parent_class else name
                kind = "method" if parent_class else "function"
                params = self._get_parameters_ts(node)
                decorators = self._get_decorators_ts(node)
                sym = Symbol(
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    parameters=params,
                    decorators=decorators,
                    parent=parent_class,
                )
                symbols.append(sym)

        # Variable declarations (const/let/var functions, arrow functions, and objects)
        if node_type == "variable_declarator":
            self._extract_variable_declarator_ts(node, symbols, parent_class)

        # Import statements
        if node_type == "import_statement":
            imp = self._parse_import_ts(node)
            if imp:
                imports.append(imp)
        elif node_type in ("lexical_declaration", "variable_declaration", "expression_statement", "assignment_expression"):
            req_imports = self._parse_require_ts_js(node)
            imports.extend(req_imports)

        # Export statements
        if node_type == "export_statement":
            exps = self._parse_export_ts(node)
            exports.extend(exps)
        elif node_type in ("expression_statement", "assignment_expression"):
            cjs_exports = self._parse_cjs_exports(node)
            exports.extend(cjs_exports)

        # Recurse into children
        for child in node.children:
            self._walk(child, symbols, imports, exports, parent_class)

    def _extract_python(self, node, symbols, imports, exports, parent_class):
        """Extract symbols from Python AST."""
        node_type = node.type

        # Class definitions
        if node_type == "class_definition":
            name = self._get_child_text(node, "identifier")
            if name:
                decorators = self._get_decorators_py(node)
                sym = Symbol(
                    name=name,
                    qualified_name=name,
                    kind="class",
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    decorators=decorators,
                )
                symbols.append(sym)
                for child in node.children:
                    self._walk(child, symbols, imports, exports, parent_class=name)
                return

        # Function definitions
        if node_type == "function_definition":
            name = self._get_child_text(node, "identifier")
            if name:
                qualified = f"{parent_class}.{name}" if parent_class else name
                kind = "method" if parent_class else "function"
                decorators = self._get_decorators_py(node)
                sym = Symbol(
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    decorators=decorators,
                    parent=parent_class,
                )
                symbols.append(sym)

        # Import statements
        if node_type in ("import_statement", "import_from_statement"):
            py_imports = self._parse_import_py(node)
            imports.extend(py_imports)

        # Recurse
        for child in node.children:
            self._walk(child, symbols, imports, exports, parent_class)

    def _extract_java(self, node, symbols, imports, exports, parent_class):
        """Extract symbols from Java AST."""
        node_type = node.type

        if node_type == "class_declaration":
            name = self._get_child_text(node, "identifier")
            if name:
                sym = Symbol(
                    name=name,
                    qualified_name=name,
                    kind="class",
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                )
                symbols.append(sym)
                for child in node.children:
                    self._walk(child, symbols, imports, exports, parent_class=name)
                return

        if node_type == "method_declaration":
            name = self._get_child_text(node, "identifier")
            if name:
                qualified = f"{parent_class}.{name}" if parent_class else name
                sym = Symbol(
                    name=name,
                    qualified_name=qualified,
                    kind="method" if parent_class else "function",
                    file_path=self.file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    parent=parent_class,
                )
                symbols.append(sym)

        for child in node.children:
            self._walk(child, symbols, imports, exports, parent_class)

    # ── Helper Methods ────────────────────────────────

    @staticmethod
    def _get_child_text(node, child_type: str) -> str | None:
        """Get the text of the first child node of a given type."""
        for child in node.children:
            if child.type == child_type:
                return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
        return None

    @staticmethod
    def _get_decorators_ts(node) -> list[str]:
        """Get decorator names from a TypeScript/JavaScript node."""
        decorators = []
        # Look for decorator nodes in the parent or siblings
        if node.parent:
            for sibling in node.parent.children:
                if sibling.type == "decorator":
                    text = sibling.text.decode("utf-8") if isinstance(sibling.text, bytes) else sibling.text
                    decorators.append(text.lstrip("@"))
        return decorators

    @staticmethod
    def _get_decorators_py(node) -> list[str]:
        """Get decorator names from a Python node."""
        decorators = []
        if node.parent:
            for sibling in node.parent.children:
                if sibling.type == "decorator" and sibling.end_point[0] < node.start_point[0]:
                    text = sibling.text.decode("utf-8") if isinstance(sibling.text, bytes) else sibling.text
                    # Extract just the decorator name
                    name = text.lstrip("@").split("(")[0].strip()
                    decorators.append(name)
        return decorators

    @staticmethod
    def _get_parameters_ts(node) -> list[str]:
        """Extract parameter names from a function/method."""
        params = []
        for child in node.children:
            if child.type == "formal_parameters":
                for param in child.children:
                    if param.type in ("required_parameter", "optional_parameter", "identifier"):
                        name = param.children[0] if param.children else param
                        text = name.text.decode("utf-8") if isinstance(name.text, bytes) else name.text
                        if text not in ("(", ")", ","):
                            params.append(text)
        return params

    @staticmethod
    def _parse_import_ts(node) -> Import | None:
        """Parse a TypeScript/JavaScript import statement."""
        try:
            module = None
            names = []
            is_default = False
            is_namespace = False
            alias = None

            for child in node.children:
                if child.type == "string":
                    module = child.text.decode("utf-8").strip("'\"") if isinstance(child.text, bytes) else child.text.strip("'\"")
                elif child.type == "import_clause":
                    for sub in child.children:
                        if sub.type == "identifier":
                            # Default import: import defaultAuth from './auth'
                            name = sub.text.decode("utf-8") if isinstance(sub.text, bytes) else sub.text
                            names.append(name)
                            is_default = True
                            alias = name
                        elif sub.type == "namespace_import":
                            # Namespace import: import * as allAuth from './all'
                            is_namespace = True
                            for n in sub.children:
                                if n.type == "identifier":
                                    name = n.text.decode("utf-8") if isinstance(n.text, bytes) else n.text
                                    names.append(name)
                                    alias = name
                        elif sub.type == "named_imports":
                            # Named imports: import { a, b as c } from './foo'
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    name_node = spec.child_by_field_name("name")
                                    alias_node = spec.child_by_field_name("alias")
                                    if not name_node:
                                        id_children = [c for c in spec.children if c.type == "identifier"]
                                        if len(id_children) == 1:
                                            name_node = id_children[0]
                                        elif len(id_children) >= 2:
                                            name_node = id_children[0]
                                            alias_node = id_children[1]

                                    if name_node:
                                        orig_name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                                        names.append(orig_name)
                                        if alias_node:
                                            local_alias = alias_node.text.decode("utf-8") if isinstance(alias_node.text, bytes) else alias_node.text
                                            if local_alias and local_alias != orig_name:
                                                names.append(local_alias)

            if module:
                return Import(
                    module=module,
                    names=names,
                    is_default=is_default,
                    is_namespace=is_namespace,
                    alias=alias,
                    line=node.start_point[0] + 1,
                )
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_require_ts_js(node) -> list[Import]:
        """Parse CommonJS require statements like const x = require('./x')."""
        results: list[Import] = []
        try:
            line = node.start_point[0] + 1
            for decl in node.children:
                if decl.type == "variable_declarator":
                    val = decl.child_by_field_name("value")
                    name_node = decl.child_by_field_name("name")
                    if not val or not name_node:
                        children = [c for c in decl.children if c.type not in ("=",)]
                        if len(children) >= 2:
                            name_node, val = children[0], children[1]
                    if val and val.type == "call_expression":
                        func = val.child_by_field_name("function") or (val.children[0] if val.children else None)
                        if not func:
                            continue
                        fname = func.text.decode("utf-8") if isinstance(func.text, bytes) else func.text
                        if fname == "require":
                            args = val.child_by_field_name("arguments")
                            module = None
                            if args:
                                for arg in args.children:
                                    if arg.type == "string":
                                        module = arg.text.decode("utf-8").strip("'\"") if isinstance(arg.text, bytes) else arg.text.strip("'\"")
                                        break
                            if module:
                                names: list[str] = []
                                is_default = False
                                if name_node.type == "identifier":
                                    id_name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                                    names.append(id_name)
                                    is_default = True
                                elif name_node.type == "object_pattern":
                                    for prop in name_node.children:
                                        if prop.type in ("shorthand_property_identifier_pattern", "identifier"):
                                            pname = prop.text.decode("utf-8") if isinstance(prop.text, bytes) else prop.text
                                            names.append(pname)
                                        elif prop.type == "pair_pattern":
                                            key = prop.child_by_field_name("key")
                                            val_sub = prop.child_by_field_name("value")
                                            if key:
                                                names.append(key.text.decode("utf-8") if isinstance(key.text, bytes) else key.text)
                                            if val_sub and val_sub != key:
                                                names.append(val_sub.text.decode("utf-8") if isinstance(val_sub.text, bytes) else val_sub.text)
                                results.append(Import(
                                    module=module,
                                    names=names,
                                    is_default=is_default,
                                    line=line,
                                ))

            # Check for barrel re-exports: module.exports.xxx = require('./xxx') or exports.xxx = require('./xxx')
            assign = node if node.type == "assignment_expression" else None
            if not assign and node.type == "expression_statement":
                for c in node.children:
                    if c.type == "assignment_expression":
                        assign = c
                        break
            if assign:
                left = assign.child_by_field_name("left")
                right = assign.child_by_field_name("right")
                if right and right.type == "call_expression":
                    func = right.child_by_field_name("function")
                    func_name = func.text.decode("utf-8") if isinstance(func.text, bytes) else (func.text if func else "")
                    if func_name == "require":
                        args = right.child_by_field_name("arguments")
                        module = None
                        if args:
                            for a in args.children:
                                if a.type == "string":
                                    module = a.text.decode("utf-8").strip("'\"") if isinstance(a.text, bytes) else a.text.strip("'\"")
                                    break
                        if module and left:
                            left_text = left.text.decode("utf-8") if isinstance(left.text, bytes) else left.text
                            prop = left_text.split(".")[-1]
                            if prop not in ("exports", "module"):
                                results.append(Import(module=module, names=[prop], line=line))
                            else:
                                results.append(Import(module=module, names=[], is_default=True, line=line))
        except Exception:
            pass
        return results

    def _extract_variable_declarator_ts(self, node, symbols: list[Symbol], parent_class: str | None = None):
        """Extract functions, methods, or objects declared via const/let/var."""
        # Only extract top-level / module-level or class-level declarations, not inner local variables
        curr = node.parent
        while curr:
            if curr.type in ("function_declaration", "arrow_function", "function_expression", "method_definition"):
                return
            curr = curr.parent

        name_node = node.child_by_field_name("name")
        val_node = node.child_by_field_name("value")
        if not name_node or name_node.type != "identifier" or not val_node:
            return

        var_name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
        if not var_name:
            return

        qualified = f"{parent_class}.{var_name}" if parent_class else var_name
        line_start = node.start_point[0] + 1
        line_end = node.end_point[0] + 1

        # 1. Direct function: const foo = () => {} or const foo = function() {}
        if val_node.type in ("arrow_function", "function_expression"):
            params = self._get_parameters_ts(val_node)
            sym = Symbol(
                name=var_name,
                qualified_name=qualified,
                kind="function",
                file_path=self.file_path,
                line_start=line_start,
                line_end=line_end,
                parameters=params,
                parent=parent_class,
            )
            symbols.append(sym)
            return

        # 2. Wrapped function: const login = catchAsync(async (req, res) => {})
        if val_node.type == "call_expression":
            args = val_node.child_by_field_name("arguments")
            has_fn_arg = False
            if args:
                has_fn_arg = any(a.type in ("arrow_function", "function_expression") for a in args.children)
            if has_fn_arg:
                sym = Symbol(
                    name=var_name,
                    qualified_name=qualified,
                    kind="function",
                    file_path=self.file_path,
                    line_start=line_start,
                    line_end=line_end,
                    parent=parent_class,
                )
                symbols.append(sym)
                return

        # 3. Object with methods: const auth = { required: jwt(), optional: jwt() }
        if val_node.type == "object":
            sym = Symbol(
                name=var_name,
                qualified_name=qualified,
                kind="variable",
                file_path=self.file_path,
                line_start=line_start,
                line_end=line_end,
                parent=parent_class,
            )
            symbols.append(sym)
            for child in val_node.children:
                if child.type == "pair":
                    key = child.child_by_field_name("key")
                    if key:
                        kname = key.text.decode("utf-8") if isinstance(key.text, bytes) else key.text
                        qname = f"{var_name}.{kname}"
                        prop_sym = Symbol(
                            name=kname,
                            qualified_name=qname,
                            kind="function",
                            file_path=self.file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            parent=var_name,
                        )
                        symbols.append(prop_sym)

    @staticmethod
    def _parse_import_py(node) -> list[Import]:
        """Parse a Python import statement."""
        imports: list[Import] = []
        try:
            line = node.start_point[0] + 1
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        mod = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                        imports.append(Import(module=mod, names=[mod], line=line))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node:
                            mod = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                            al = alias_node.text.decode("utf-8") if isinstance(alias_node.text, bytes) else (alias_node.text if alias_node else None)
                            names = [mod, al] if al else [mod]
                            imports.append(Import(module=mod, names=names, alias=al, line=line))
            elif node.type == "import_from_statement":
                module_name = ""
                names = []
                is_after_import = False
                for child in node.children:
                    if child.type == "from":
                        continue
                    elif child.type == "import":
                        is_after_import = True
                        continue

                    if not is_after_import:
                        if child.type in ("dotted_name", "relative_import"):
                            module_name = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                    else:
                        if child.type == "dotted_name":
                            n = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                            names.append(n)
                        elif child.type == "aliased_import":
                            name_node = child.child_by_field_name("name")
                            alias_node = child.child_by_field_name("alias")
                            if name_node:
                                orig = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                                names.append(orig)
                            if alias_node:
                                al = alias_node.text.decode("utf-8") if isinstance(alias_node.text, bytes) else alias_node.text
                                if al and al not in names:
                                    names.append(al)
                        elif child.type == "wildcard_import":
                            names.append("*")
                if module_name:
                    imports.append(Import(module=module_name, names=names, line=line))
        except Exception:
            pass
        return imports

    @staticmethod
    def _parse_export_ts(node) -> list[Export]:
        """Parse a TypeScript/JavaScript export statement."""
        exports: list[Export] = []
        try:
            line = node.start_point[0] + 1
            is_default = any(
                c.type == "default" or (isinstance(c.text, bytes) and c.text == b"default")
                for c in node.children
            )
            for child in node.children:
                if child.type in ("class_declaration", "function_declaration"):
                    name_node = None
                    for c in child.children:
                        if c.type in ("identifier", "type_identifier"):
                            name_node = c
                            break
                    if name_node:
                        name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                        exports.append(Export(name=name, is_default=is_default, line=line))
                elif child.type in ("lexical_declaration", "variable_declaration"):
                    for decl in child.children:
                        if decl.type == "variable_declarator":
                            name_node = decl.child_by_field_name("name")
                            if name_node:
                                name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                                exports.append(Export(name=name, is_default=is_default, line=line))
                elif child.type == "export_clause":
                    for spec in child.children:
                        if spec.type == "export_specifier":
                            alias_node = spec.child_by_field_name("alias")
                            name_node = spec.child_by_field_name("name")
                            target = alias_node or name_node
                            if not target:
                                ids = [c for c in spec.children if c.type == "identifier"]
                                target = ids[-1] if ids else None
                            if target:
                                name = target.text.decode("utf-8") if isinstance(target.text, bytes) else target.text
                                exports.append(Export(name=name, is_default=is_default, line=line))
                elif is_default and child.type == "identifier":
                    name = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                    exports.append(Export(name=name, is_default=True, line=line))
        except Exception:
            pass
        return exports

    @staticmethod
    def _parse_cjs_exports(node) -> list[Export]:
        """Parse CommonJS exports like module.exports = { a, b } or module.exports = router."""
        exports: list[Export] = []
        try:
            line = node.start_point[0] + 1
            assign = node if node.type == "assignment_expression" else None
            if not assign and node.type == "expression_statement":
                for c in node.children:
                    if c.type == "assignment_expression":
                        assign = c
                        break
            if assign:
                left = assign.child_by_field_name("left")
                right = assign.child_by_field_name("right")
                if left and right:
                    left_text = left.text.decode("utf-8") if isinstance(left.text, bytes) else left.text
                    if left_text in ("module.exports", "exports"):
                        if right.type == "object":
                            for child in right.children:
                                if child.type == "shorthand_property_identifier":
                                    pname = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                                    exports.append(Export(name=pname, is_default=False, line=line))
                                elif child.type == "pair":
                                    k = child.child_by_field_name("key")
                                    if k:
                                        pname = k.text.decode("utf-8") if isinstance(k.text, bytes) else k.text
                                        exports.append(Export(name=pname, is_default=False, line=line))
                        elif right.type == "identifier":
                            rname = right.text.decode("utf-8") if isinstance(right.text, bytes) else right.text
                            exports.append(Export(name=rname, is_default=True, line=line))
                    elif left_text.startswith("module.exports.") or left_text.startswith("exports."):
                        prop = left_text.split(".")[-1]
                        if prop not in ("exports", "module"):
                            exports.append(Export(name=prop, is_default=False, line=line))
        except Exception:
            pass
        return exports


# ── Main Parser ───────────────────────────────────────


class ASTParser:
    """Multi-language AST parser with incremental parsing support.

    Uses tree-sitter for fast, error-tolerant, incremental parsing.
    Caches parsed trees per file for efficient incremental updates.
    """

    def __init__(self, cache_size: int = 500):
        self._tree_cache: dict[str, object] = {}
        self._cache_size = cache_size

    def parse(self, source: str | bytes, language: str, file_path: str = "") -> ParseResult:
        """Parse source code and extract symbols.

        Args:
            source: Source code as string or bytes.
            language: Language name (e.g. "typescript", "python").
            file_path: Path to the file being parsed.

        Returns:
            ParseResult with tree, symbols, imports, exports, and errors.
        """
        if isinstance(source, str):
            source = source.encode("utf-8")

        parser = self._get_parser(language)
        tree = parser.parse(source)

        # Cache the tree for incremental parsing
        if file_path:
            self._manage_cache(file_path, tree)

        # Extract symbols
        extractor = SymbolExtractor(language, file_path)
        symbols, imports, exports = extractor.extract(tree.root_node)

        # Collect parse errors
        errors = self._collect_errors(tree.root_node)

        return ParseResult(
            tree=tree,
            language=language,
            file_path=file_path,
            symbols=symbols,
            imports=imports,
            exports=exports,
            errors=errors,
        )

    def parse_file(self, file_path: str) -> ParseResult | None:
        """Parse a file from disk.

        Args:
            file_path: Absolute or relative path to the file.

        Returns:
            ParseResult or None if the language is unsupported.
        """
        language = detect_language(file_path)
        if not language:
            return None

        try:
            source = Path(file_path).read_bytes()
            return self.parse(source, language, file_path)
        except (OSError, FileNotFoundError) as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return None

    def incremental_parse(
        self,
        source: bytes,
        file_path: str,
        start_byte: int,
        old_end_byte: int,
        new_end_byte: int,
        start_point: tuple[int, int],
        old_end_point: tuple[int, int],
        new_end_point: tuple[int, int],
    ) -> ParseResult | None:
        """Incrementally re-parse a file after an edit.

        Only re-parses the affected nodes, not the entire file.
        Falls back to full parse if no cached tree exists.

        Args:
            source: Updated full source code.
            file_path: Path to the file.
            start_byte, old_end_byte, new_end_byte: Byte offsets of the edit.
            start_point, old_end_point, new_end_point: Row/col of the edit.

        Returns:
            ParseResult with updated tree and symbols.
        """
        language = detect_language(file_path)
        if not language:
            return None

        old_tree = self._tree_cache.get(file_path)
        if not old_tree:
            # No cached tree — do full parse
            return self.parse(source, language, file_path)

        # Apply edit to old tree
        old_tree.edit(  # type: ignore[attr-defined]
            start_byte=start_byte,
            old_end_byte=old_end_byte,
            new_end_byte=new_end_byte,
            start_point=start_point,
            old_end_point=old_end_point,
            new_end_point=new_end_point,
        )

        # Incremental parse
        parser = self._get_parser(language)
        new_tree = parser.parse(source, old_tree)
        self._manage_cache(file_path, new_tree)

        extractor = SymbolExtractor(language, file_path)
        symbols, imports, exports = extractor.extract(new_tree.root_node)
        errors = self._collect_errors(new_tree.root_node)

        return ParseResult(
            tree=new_tree,
            language=language,
            file_path=file_path,
            symbols=symbols,
            imports=imports,
            exports=exports,
            errors=errors,
        )

    def _get_parser(self, language: str):
        """Get or create a tree-sitter parser for a language."""
        return get_parser(language)

    def _manage_cache(self, file_path: str, tree: object) -> None:
        """Manage the tree cache with LRU eviction."""
        if len(self._tree_cache) >= self._cache_size:
            # Evict oldest entry
            oldest_key = next(iter(self._tree_cache))
            del self._tree_cache[oldest_key]
        self._tree_cache[file_path] = tree

    def _collect_errors(self, node) -> list[ParseError]:
        """Walk the AST and collect any ERROR nodes."""
        errors = []
        if node.type == "ERROR" or node.is_missing:
            errors.append(
                ParseError(
                    message=f"Parse error at node: {node.type}",
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                )
            )
        for child in node.children:
            errors.extend(self._collect_errors(child))
        return errors

    def clear_cache(self) -> None:
        """Clear the tree cache."""
        self._tree_cache.clear()

    @property
    def cached_files(self) -> int:
        """Number of files with cached parse trees."""
        return len(self._tree_cache)

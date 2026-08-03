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

        # Import statements
        if node_type == "import_statement":
            imp = self._parse_import_ts(node)
            if imp:
                imports.append(imp)

        # Export statements
        if node_type == "export_statement":
            exp = self._parse_export_ts(node)
            if exp:
                exports.append(exp)

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
            imp = self._parse_import_py(node)
            if imp:
                imports.append(imp)

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
            # Extract module path from the source
            for child in node.children:
                if child.type == "string":
                    module = child.text.decode("utf-8").strip("'\"") if isinstance(child.text, bytes) else child.text.strip("'\"")
                    return Import(
                        module=module,
                        names=[],  # simplified — full parsing in Phase 2
                        line=node.start_point[0] + 1,
                    )
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_import_py(node) -> Import | None:
        """Parse a Python import statement."""
        try:
            if node.type == "import_from_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        module = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                        return Import(
                            module=module,
                            names=[],
                            line=node.start_point[0] + 1,
                        )
            elif node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        module = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                        return Import(
                            module=module,
                            names=[module],
                            line=node.start_point[0] + 1,
                        )
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_export_ts(node) -> Export | None:
        """Parse a TypeScript/JavaScript export statement."""
        try:
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
                        return Export(name=name, is_default=is_default, line=node.start_point[0] + 1)
        except Exception:
            pass
        return None


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

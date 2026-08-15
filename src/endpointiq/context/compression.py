"""4-stage code compression pipeline + token counting.

Compresses source code while preserving semantic meaning, applied
progressively until the token budget is met:

Stage 1: Import Pruner     — remove unreferenced imports (~5% reduction)
Stage 2: Comment Stripper  — strip comments, keep JSDoc for public APIs (~10%)
Stage 3: Whitespace Normalizer — collapse blank lines, trim trailing spaces (~5%)
Stage 4: Method Summarizer — replace irrelevant method bodies with signatures (~30%)

Also provides a tiktoken-based token counter for accurate budget tracking.
"""

from __future__ import annotations

import logging
import re

import tiktoken

logger = logging.getLogger(__name__)

# Shared encoder for token counting (cl100k_base is used by most modern models)
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Lazily initialize the tiktoken encoder."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string using tiktoken.

    Uses cl100k_base encoding (compatible with GPT-4, Llama, etc.).
    """
    if not text:
        return 0
    encoder = _get_encoder()
    return len(encoder.encode(text))


# ── Stage 1: Import Pruner ────────────────────────────


def prune_imports(source: str) -> str:
    """Remove import statements that are not referenced in the rest of the code.

    Scans the code body (everything after imports) for references to
    imported names. Removes import lines where no imported name appears
    in the body.

    This is a lossless transformation.
    """
    lines = source.split("\n")
    import_lines: list[int] = []
    import_names: dict[int, list[str]] = {}

    # Identify import lines and extract imported names
    for i, line in enumerate(lines):
        stripped = line.strip()

        # TypeScript/JavaScript imports
        # import { Foo, Bar } from './module';
        match = re.match(
            r"import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+['\"]", stripped
        )
        if match:
            import_lines.append(i)
            names_str = match.group(1) or match.group(2) or ""
            names = [n.strip().split(" as ")[-1].strip() for n in names_str.split(",")]
            import_names[i] = [n for n in names if n]
            continue

        # Python imports
        # from module import Foo, Bar
        match = re.match(r"from\s+\S+\s+import\s+(.+)", stripped)
        if match:
            import_lines.append(i)
            names_str = match.group(1)
            names = [n.strip().split(" as ")[-1].strip() for n in names_str.split(",")]
            import_names[i] = [n for n in names if n]
            continue

        # import module
        match = re.match(r"import\s+(\w+)", stripped)
        if match and "from" not in stripped:
            import_lines.append(i)
            import_names[i] = [match.group(1)]

    if not import_lines:
        return source

    # Build the body text (everything that's not an import)
    body_lines = [
        lines[i] for i in range(len(lines)) if i not in import_lines
    ]
    body_text = "\n".join(body_lines)

    # Check which imports are referenced in the body
    lines_to_remove: set[int] = set()
    for line_idx, names in import_names.items():
        if not any(re.search(rf'\b{re.escape(name)}\b', body_text) for name in names):
            lines_to_remove.add(line_idx)

    if not lines_to_remove:
        return source

    result = [lines[i] for i in range(len(lines)) if i not in lines_to_remove]
    return "\n".join(result)


# ── Stage 2: Comment Stripper ─────────────────────────


def strip_comments(source: str, keep_jsdoc: bool = True) -> str:
    """Remove comments from source code.

    Removes:
    - Single-line comments (// ...)
    - Multi-line comments (/* ... */)
    - Python comments (# ...)

    Optionally keeps JSDoc comments (/** ... */) for public API documentation.

    This is a near-lossless transformation.
    """
    # Remove multi-line comments
    if keep_jsdoc:
        # Remove /* ... */ but NOT /** ... */
        source = re.sub(r'/\*(?!\*).*?\*/', '', source, flags=re.DOTALL)
    else:
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)

    lines = source.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()

        # Skip pure comment lines
        if stripped.startswith("//") and not stripped.startswith("///"):
            continue
        if stripped.startswith("#") and not stripped.startswith("#!"):
            continue

        # Remove inline comments (// at end of line)
        # Be careful not to remove // inside strings
        line = _remove_inline_comment(line)

        result.append(line)

    return "\n".join(result)


def _remove_inline_comment(line: str) -> str:
    """Remove inline // comments while preserving strings."""
    in_single_quote = False
    in_double_quote = False
    in_template = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '\\' and i + 1 < len(line):
            i += 2  # skip escaped character
            continue
        if ch == "'" and not in_double_quote and not in_template:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote and not in_template:
            in_double_quote = not in_double_quote
        elif ch == '`' and not in_single_quote and not in_double_quote:
            in_template = not in_template
        elif (
            ch == '/' and i + 1 < len(line) and line[i + 1] == '/'
            and not in_single_quote and not in_double_quote and not in_template
        ):
            return line[:i].rstrip()
        i += 1
    return line


# ── Stage 3: Whitespace Normalizer ────────────────────


def normalize_whitespace(source: str) -> str:
    """Collapse multiple blank lines and trim trailing whitespace.

    Rules:
    - Maximum 1 consecutive blank line
    - Remove trailing whitespace from each line
    - Trim leading/trailing blank lines

    This is a lossless transformation.
    """
    lines = source.split("\n")
    result: list[str] = []
    prev_blank = False

    for line in lines:
        stripped_line = line.rstrip()
        is_blank = len(stripped_line) == 0

        if is_blank and prev_blank:
            continue  # Skip consecutive blanks

        result.append(stripped_line)
        prev_blank = is_blank

    # Trim leading/trailing blank lines
    while result and not result[0]:
        result.pop(0)
    while result and not result[-1]:
        result.pop()

    return "\n".join(result)


# ── Stage 4: Method Summarizer ────────────────────────


def summarize_methods(source: str, relevant_names: set[str] | None = None) -> str:
    """Replace irrelevant method bodies with signature-only stubs.

    Keeps the full body of methods whose names are in `relevant_names`.
    For all other methods, replaces the body with `{ /* ... */ }`.

    This is a lossy transformation but preserves the API surface.

    Args:
        source: Source code to compress.
        relevant_names: Set of method/function names to keep in full.
                        If None, keeps all methods.
    """
    if relevant_names is None:
        return source

    lines = source.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Detect method/function declarations
        method_match = re.match(
            r'(\s*(?:async\s+)?(?:(?:public|private|protected|static)\s+)*'
            r'(?:function\s+)?(\w+)\s*\([^)]*\)(?:\s*:\s*\S+)?\s*)\{',
            line
        )

        if method_match:
            method_name = method_match.group(2)

            if method_name in relevant_names:
                # Keep the full method body
                result.append(line)
                i += 1
            else:
                # Replace with signature only
                signature = method_match.group(1).rstrip()
                result.append(f"{signature} {{ /* ... */ }}")

                # Skip the method body by counting braces
                brace_count = line.count("{") - line.count("}")
                i += 1
                while i < len(lines) and brace_count > 0:
                    brace_count += lines[i].count("{") - lines[i].count("}")
                    i += 1
        else:
            result.append(line)
            i += 1

    return "\n".join(result)


# ── Full Pipeline ─────────────────────────────────────


def compress(
    source: str,
    token_budget: int | None = None,
    relevant_names: set[str] | None = None,
) -> str:
    """Apply the full 4-stage compression pipeline adaptively.

    Applies stages in order and stops early if the result is
    within the token budget.

    Args:
        source: Raw source code.
        token_budget: Target token count (optional).
        relevant_names: Method names to keep in full for Stage 4.

    Returns:
        Compressed source code.
    """
    result = source

    # Stage 1: Import Pruning
    result = prune_imports(result)
    if token_budget and count_tokens(result) <= token_budget:
        return result

    # Stage 2: Comment Stripping
    result = strip_comments(result)
    if token_budget and count_tokens(result) <= token_budget:
        return result

    # Stage 3: Whitespace Normalization
    result = normalize_whitespace(result)
    if token_budget and count_tokens(result) <= token_budget:
        return result

    # Stage 4: Method Summarization (lossy)
    result = summarize_methods(result, relevant_names)

    return result

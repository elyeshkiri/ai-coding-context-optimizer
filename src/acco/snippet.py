"""Pull one symbol out of a file so the model never needs the rest."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .skeleton import PYTHON_SUFFIXES, _node_start


def _python_span(text: str, name: str) -> tuple[int, int] | None:
    """Handle python span."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Source has syntax errors; use an explicit range") from exc
    hits = []
    def walk(node, parents=()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualified = ".".join((*parents, node.name))
            if qualified == name or ("." not in name and node.name == name):
                hits.append((_node_start(node), node.end_lineno, qualified))
            parents = (*parents, node.name)
        for child in ast.iter_child_nodes(node): walk(child, parents)
    walk(tree)
    if len(hits) > 1:
        raise ValueError("Ambiguous symbol; use a qualified name: " + ", ".join(h[2] for h in hits))
    return hits[0][:2] if hits else None


_DECL = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:public\s+|private\s+|protected\s+|static\s+)*"
    r"(?:function|func|fn|def|class|interface|struct|enum|type|impl)\s+(\w+)",
)


def _pattern_span(text: str, name: str) -> tuple[int, int] | None:
    """Handle pattern span."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines, 1):
        m = _DECL.match(ln)
        if m and m.group(1) == name:
            start = i
            break
        if re.search(rf"\b{re.escape(name)}\s*\(", ln) and (
            "function" in ln or "=>" in ln or "def " in ln
        ):
            start = i
            break
    if start is None:
        return None
    # Other languages are explicitly approximate, never silently cut at 120 lines.
    end = len(lines)
    start_indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
    for i in range(start + 1, len(lines) + 1):
        ln = lines[i - 1]
        if not ln.strip():
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= start_indent and i > start + 1 and _DECL.match(ln):
            end = i - 1
            break
    return start, end


def extract_symbol(text: str, suffix: str, name: str) -> tuple[str, int, int] | None:
    """Return (snippet, start_line, end_line) or None if the symbol is missing."""
    from .syntax import JS_TS, STRUCTURED_EXTRA, extract

    lowered = suffix.lower()
    if lowered in JS_TS:
        return extract(text, lowered, name)
    if lowered in STRUCTURED_EXTRA:
        return extract(text, lowered, name)
    span = None
    if lowered in PYTHON_SUFFIXES:
        span = _python_span(text, name)
    if span is None and lowered not in PYTHON_SUFFIXES:
        span = _pattern_span(text, name)
    if span is None:
        return None
    start, end = span
    lines = text.splitlines()
    body = "\n".join(lines[start - 1 : end]) + "\n"
    label = "" if lowered in PYTHON_SUFFIXES else " (approximate boundaries; verify source)"
    header = f"# {name}  lines {start}-{end}{label}\n"
    return header + body, start, end


def extract_from_path(path: Path, name: str) -> tuple[str, int, int] | None:
    """Extract from path."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return extract_symbol(text, path.suffix, name)

#!/usr/bin/env python3
"""Insert concise docstrings into undocumented source definitions.

This is a one-time maintenance helper for the 100% docstring coverage migration.
It intentionally follows the same scope as the Interrogate configuration:
modules, classes, top-level functions, and methods are documented; nested
functions, magic methods, and __init__ methods are left to the configured
coverage exclusions.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "token_saver"

VERB_PHRASES = {
    "add": "Add",
    "analyze": "Analyze",
    "apply": "Apply",
    "audit": "Audit",
    "build": "Build",
    "call": "Call",
    "check": "Check",
    "classify": "Classify",
    "collect": "Collect",
    "compare": "Compare",
    "compact": "Compact",
    "compress": "Compress",
    "count": "Count",
    "create": "Create",
    "decide": "Decide",
    "detect": "Detect",
    "disable": "Disable",
    "estimate": "Estimate",
    "evaluate": "Evaluate",
    "expand": "Expand",
    "explain": "Explain",
    "extract": "Extract",
    "filter": "Filter",
    "find": "Find",
    "format": "Format",
    "get": "Return",
    "handle": "Handle",
    "inspect": "Inspect",
    "install": "Install",
    "load": "Load",
    "merge": "Merge",
    "parse": "Parse",
    "plan": "Plan",
    "prune": "Prune",
    "rank": "Rank",
    "read": "Read",
    "record": "Record",
    "recover": "Recover",
    "refresh": "Refresh",
    "render": "Render",
    "reset": "Reset",
    "resolve": "Resolve",
    "retrieve": "Retrieve",
    "run": "Run",
    "save": "Save",
    "scan": "Scan",
    "serve": "Serve",
    "snapshot": "Return",
    "strip": "Strip",
    "update": "Update",
    "validate": "Validate",
    "walk": "Yield",
    "write": "Write",
}


def words(name: str) -> str:
    """Convert an identifier into a readable lower-case phrase."""
    value = name.strip("_")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return value.replace("_", " ").lower().strip()


def module_doc(path: Path) -> str:
    """Return a concise module-level description."""
    phrase = words(path.stem)
    special = {
        "__init__": "Expose the Token Saver package metadata.",
        "cli": "Implement the legacy Token Saver command-line interface.",
        "commands": "Implement high-value Token Saver command-line commands.",
        "entry": "Dispatch the Token Saver command-line entry point.",
        "mcp": "Implement the Token Saver MCP server.",
        "repo_index": "Build and query the repository source index.",
        "state": "Persist bounded local Token Saver session state.",
        "syntax": "Extract structured symbols from supported source languages.",
    }
    return special.get(path.stem, f"Provide {phrase} utilities for Token Saver.")


def class_doc(name: str) -> str:
    """Return a concise class description."""
    phrase = words(name)
    if name.endswith("Processor"):
        return f"Process {phrase.removesuffix(' processor')} command output."
    if name.endswith("Report"):
        return f"Represent a {phrase.removesuffix(' report')} report."
    if name.endswith("Result"):
        return f"Represent a {phrase.removesuffix(' result')} result."
    if name.endswith("Record"):
        return f"Represent a {phrase.removesuffix(' record')} record."
    if name.endswith("Item"):
        return f"Represent a {phrase.removesuffix(' item')} item."
    if name.endswith("Policy"):
        return f"Represent a {phrase.removesuffix(' policy')} policy."
    return f"Represent {phrase} state and behavior."


def function_doc(name: str, owner: str | None) -> str:
    """Return a concise function or method description."""
    clean = name.strip("_")
    phrase = words(clean)
    if clean == "main":
        return "Run the command-line entry point."
    if clean == "to_dict":
        return "Return a dictionary representation."
    if clean == "matches":
        return "Return whether this processor matches the command."
    if clean == "compress":
        return "Compress command output while preserving required evidence."
    if clean.startswith(("is_", "has_", "should_", "seen_", "looks_like_")):
        return f"Return whether {phrase.replace('is ', '', 1).replace('has ', '', 1)}."
    if clean.endswith("_main"):
        return f"Run the {words(clean[:-5])} command."
    first, _, rest = clean.partition("_")
    verb = VERB_PHRASES.get(first)
    if verb:
        target = words(rest) if rest else (words(owner) if owner else "the requested value")
        return f"{verb} {target}."
    if owner:
        return f"Return {phrase} for {words(owner)}."
    return f"Handle {phrase}."


def already_documented(node: ast.AST) -> bool:
    """Return whether an AST node already has a docstring."""
    return ast.get_docstring(node, clean=False) is not None


def relevant_children(node: ast.AST):
    """Yield definitions counted by the configured docstring policy."""
    body = getattr(node, "body", [])
    for child in body:
        if isinstance(child, ast.ClassDef):
            yield child, None
            for member in child.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if member.name == "__init__":
                        continue
                    if member.name.startswith("__") and member.name.endswith("__"):
                        continue
                    yield member, child.name
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if child.name.startswith("__") and child.name.endswith("__"):
                continue
            yield child, None


def indent_for_body(lines: list[str], node: ast.AST) -> str:
    """Return indentation appropriate for a definition body."""
    body = getattr(node, "body", [])
    if body:
        line = lines[body[0].lineno - 1]
        match = re.match(r"[ \t]*", line)
        if match and len(match.group(0)) > getattr(node, "col_offset", 0):
            return match.group(0)
    return " " * (getattr(node, "col_offset", 0) + 4)


def insert_docstrings(path: Path) -> int:
    """Insert missing docstrings in one Python source file."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines(keepends=True)
    edits: list[tuple[int, str]] = []

    if not already_documented(tree):
        pos = 0
        if lines and lines[0].startswith("#!"):
            pos = 1
        if pos < len(lines) and re.match(r"#.*coding[:=]", lines[pos]):
            pos += 1
        edits.append((pos, f'"""{module_doc(path)}"""\n\n'))

    for node, owner in relevant_children(tree):
        if already_documented(node):
            continue
        if isinstance(node, ast.ClassDef):
            doc = class_doc(node.name)
        else:
            doc = function_doc(node.name, owner)
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        indent = indent_for_body(lines, node)

        line_index = first.lineno - 1
        line = lines[line_index]
        start = getattr(first, "col_offset", 0)
        header = line[:start].rstrip()
        # A suite may be inline even when the function signature spans
        # multiple physical lines, e.g. the Protocol form:
        #     def f(
        #         ...
        #     ) -> T: ...
        # Detect it from the text before the first body node, not by comparing
        # the body's line number with the definition's first line.
        if header.endswith(":"):
            statement = line[start:].lstrip()
            newline = "\n" if line.endswith("\n") else ""
            replacement = (
                header + "\n"
                + indent + f'"""{doc}"""\n'
                + indent + statement.rstrip("\n") + newline
            )
            edits.append((line_index, replacement, "replace"))
        else:
            edits.append((first.lineno - 1, indent + f'"""{doc}"""\n'))

    if not edits:
        return 0

    # Apply bottom-up so AST line numbers remain valid.
    for edit in sorted(edits, key=lambda item: item[0], reverse=True):
        index, value, *mode = edit
        if mode and mode[0] == "replace":
            lines[index] = value
        else:
            lines.insert(index, value)

    updated = "".join(lines)
    # Refuse to write syntactically invalid output.
    ast.parse(updated, filename=str(path))
    path.write_text(updated, encoding="utf-8")
    return len(edits)


def main() -> int:
    """Add missing docstrings to all Token Saver source modules."""
    files = sorted(SOURCE.rglob("*.py"))
    changes = 0
    touched = 0
    for path in files:
        count = insert_docstrings(path)
        if count:
            touched += 1
            changes += count
            print(f"{path.relative_to(ROOT)}: +{count}")
    print(f"Inserted {changes} docstrings across {touched} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

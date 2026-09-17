"""Lightweight JS/TS module-aware semantic references.

This layer complements Tree-sitter symbol ranges with import-binding knowledge.
It resolves aliases/re-exports without requiring a Node runtime or a language
server, and deliberately limits itself to statically-decidable module syntax.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_NAMED_IMPORT = re.compile(
    r"\bimport\s+(?:type\s+)?\{(?P<items>[^}]+)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.S,
)
_DEFAULT_IMPORT = re.compile(
    r"\bimport\s+(?:type\s+)?(?P<local>[A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.S,
)
_NAMESPACE_IMPORT = re.compile(
    r"\bimport\s+\*\s+as\s+(?P<local>[A-Za-z_$][\w$]*)\s+from\s+['\"](?P<module>[^'\"]+)['\"]"
)
_NAMED_EXPORT = re.compile(
    r"\bexport\s+(?:type\s+)?\{(?P<items>[^}]+)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.S,
)
_STAR_EXPORT = re.compile(r"\bexport\s+\*\s+from\s+['\"](?P<module>[^'\"]+)['\"]")
_REQUIRE_DESTRUCTURE = re.compile(
    r"\b(?:const|let|var)\s+\{(?P<items>[^}]+)\}\s*=\s*require\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)",
    re.S,
)
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")


def _named_items(raw: str, *, export: bool = False) -> list[tuple[str, str]]:
    """Return (remote, local/public) bindings from a `{ ... }` clause."""
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        item = re.sub(r"^type\s+", "", item)
        bits = re.split(r"\s+as\s+|\s*:\s*", item, maxsplit=1)
        remote = bits[0].strip()
        local = bits[1].strip() if len(bits) == 2 else remote
        if re.fullmatch(r"[A-Za-z_$][\w$]*", remote) and re.fullmatch(
            r"[A-Za-z_$][\w$]*", local
        ):
            out.append((remote, local))
    return out


def extract_module_refs(text: str) -> list[dict[str, str]]:
    """Extract called imported bindings and re-exports from JS/TS source.

    Each record has `module`, `symbol`, `local`, and `kind`. `symbol="*"`
    denotes a module-level dependency such as `export *`.
    """
    calls = {match.group(1) for match in _CALL.finditer(text)}
    bare_calls = {value.split(".")[-1] for value in calls}
    refs: list[dict[str, str]] = []

    for match in _NAMED_IMPORT.finditer(text):
        module = match.group("module")
        for remote, local in _named_items(match.group("items")):
            if local in bare_calls:
                refs.append({
                    "module": module, "symbol": remote, "local": local,
                    "kind": "semantic-call",
                })

    for match in _DEFAULT_IMPORT.finditer(text):
        local = match.group("local")
        if local in bare_calls:
            refs.append({
                "module": match.group("module"), "symbol": "default", "local": local,
                "kind": "semantic-call",
            })

    for match in _NAMESPACE_IMPORT.finditer(text):
        local = match.group("local")
        prefix = local + "."
        for call in calls:
            if call.startswith(prefix):
                refs.append({
                    "module": match.group("module"),
                    "symbol": call[len(prefix):].split(".")[-1],
                    "local": call,
                    "kind": "semantic-call",
                })

    for match in _REQUIRE_DESTRUCTURE.finditer(text):
        module = match.group("module")
        for remote, local in _named_items(match.group("items")):
            if local in bare_calls:
                refs.append({
                    "module": module, "symbol": remote, "local": local,
                    "kind": "semantic-call",
                })

    for match in _NAMED_EXPORT.finditer(text):
        module = match.group("module")
        for remote, public in _named_items(match.group("items"), export=True):
            refs.append({
                "module": module, "symbol": remote, "local": public,
                "kind": "reexport",
            })
    for match in _STAR_EXPORT.finditer(text):
        refs.append({
            "module": match.group("module"), "symbol": "*", "local": "*",
            "kind": "reexport",
        })

    unique = {
        (ref["module"], ref["symbol"], ref["local"], ref["kind"]): ref
        for ref in refs
    }
    return [unique[key] for key in sorted(unique)]


def resolve_module_path(
    source_rel: str, module: str, known_paths: Iterable[str],
) -> str | None:
    """Resolve a relative JS/TS module specifier against indexed paths."""
    if not module.startswith("."):
        return None
    known = set(known_paths)
    source_dir = Path(source_rel).parent
    raw = (source_dir / module).as_posix()
    # Path('a/../b') does not normalize lexically, so collapse components
    # without touching the filesystem.
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    base = "/".join(parts)
    suffixes = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
    candidates = [base + suffix for suffix in suffixes]
    candidates.extend(
        f"{base}/index{suffix}" for suffix in suffixes[1:]
    )
    return next((candidate for candidate in candidates if candidate in known), None)

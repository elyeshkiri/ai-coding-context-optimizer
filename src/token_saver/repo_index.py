"""Incremental repository index and lightweight code relationship graph.

The index is deliberately dependency-free.  It extracts imports, declarations,
and call-like identifiers, persists records by content digest, and only reparses
files whose bytes changed.  Language-aware parsers can replace individual
extractors later without changing the on-disk format.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .skeleton import walk_repo

INDEX_VERSION = 1
_IDENT = re.compile(r"\b[A-Za-z_$][\w$]*\b")
_DECL = re.compile(
    r"\b(?:class|interface|type|enum|struct|trait|def|function|func|fn)\s+([A-Za-z_$][\w$]*)"
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?:=|:)"
)
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_IMPORT = re.compile(
    r"(?:from\s+['\"]([^'\"]+)['\"]|require\s*\(\s*['\"]([^'\"]+)['\"]|"
    r"(?:import|from|use)\s+([\w./@-]+))"
)
_CALL_STOP = {"if", "for", "while", "switch", "catch", "return", "function", "def", "class"}


@dataclass
class FileRecord:
    path: str
    digest: str
    size: int
    symbols: list[str]
    imports: list[str]
    calls: list[str]
    tokens: list[str]


@dataclass
class RepositoryIndex:
    root: Path
    records: dict[str, FileRecord]
    reparsed: int = 0
    reused: int = 0

    def neighbors(self, rel: str) -> list[tuple[str, str]]:
        """Return related files and the edge that connected them."""
        source = self.records.get(rel)
        if source is None:
            return []
        source_stem = Path(rel).stem.lower()
        source_symbols = {s.lower() for s in source.symbols}
        out: dict[str, str] = {}
        for other_rel, other in self.records.items():
            if other_rel == rel:
                continue
            other_stem = Path(other_rel).stem.lower()
            imports = {Path(value).name.lower() for value in other.imports}
            reverse_imports = {Path(value).name.lower() for value in source.imports}
            if source_stem in imports or any(source_stem == value.split(".")[-1] for value in imports):
                out[other_rel] = "imported-by"
            elif other_stem in reverse_imports or any(other_stem == value.split(".")[-1] for value in reverse_imports):
                out[other_rel] = "imports"
            elif source_symbols & {call.split(".")[-1].lower() for call in other.calls}:
                out[other_rel] = "calls-symbol"
            elif {s.lower() for s in other.symbols} & {call.split(".")[-1].lower() for call in source.calls}:
                out[other_rel] = "calls"
        return sorted(out.items())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _extract_python(text: str) -> tuple[set[str], set[str], set[str]]:
    symbols: set[str] = set()
    imports: set[str] = set()
    calls: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports, calls
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                calls.add(target.id)
            elif isinstance(target, ast.Attribute):
                calls.add(target.attr)
    return symbols, imports, calls


def _extract(text: str, suffix: str) -> tuple[list[str], list[str], list[str], list[str]]:
    if suffix.lower() in {".py", ".pyi"}:
        symbols, imports, calls = _extract_python(text)
    else:
        symbols = {a or b for a, b in _DECL.findall(text)}
        imports = {next(value for value in groups if value) for groups in _IMPORT.findall(text)}
        calls = {match.group(1).split(".")[-1] for match in _CALL.finditer(text)} - _CALL_STOP
    tokens = sorted({value.lower() for value in _IDENT.findall(text) if len(value) > 2})
    return sorted(symbols), sorted(imports), sorted(calls), tokens


def _default_cache(root: Path) -> Path:
    state = os.environ.get("TOKEN_SAVER_STATE_DIR")
    base = Path(state).expanduser() if state else Path.home() / ".claude" / "token-saver"
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return base / "indexes" / f"{key}.json"


def _load(path: Path) -> dict[str, FileRecord]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != INDEX_VERSION:
            return {}
        return {key: FileRecord(**value) for key, value in payload.get("records", {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def _save(path: Path, records: dict[str, FileRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": INDEX_VERSION, "records": {key: asdict(value) for key, value in records.items()}}
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def build_index(
    root: Path, *, use_gitignore: bool = True, cache_path: Path | None = None,
    persist: bool = True,
) -> RepositoryIndex:
    root = root.resolve()
    target = cache_path or _default_cache(root)
    old = _load(target) if persist else {}
    records: dict[str, FileRecord] = {}
    reparsed = reused = 0
    for path in walk_repo(root, use_gitignore=use_gitignore):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        digest = _digest(text)
        if rel in old and old[rel].digest == digest:
            records[rel] = old[rel]
            reused += 1
            continue
        symbols, imports, calls, tokens = _extract(text, path.suffix)
        records[rel] = FileRecord(rel, digest, len(text.encode()), symbols, imports, calls, tokens)
        reparsed += 1
    if persist:
        _save(target, records)
    return RepositoryIndex(root, records, reparsed, reused)


def similarity(left: FileRecord, right: FileRecord) -> float:
    """Jaccard similarity over identifiers; robust to whitespace/comment churn."""
    a, b = set(left.tokens), set(right.tokens)
    return len(a & b) / len(a | b) if a and b else 0.0

"""Incremental content-addressed source index for task-aware context packing.

The index stores only compact structural/search metadata, never full source text.
Unchanged files are reused by size+mtime fast path; when metadata changes, a
SHA-256 digest detects timestamp-only changes so expensive parsing can still be
reused. Exact source is read only for files that survive ranking.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .skeleton import skeletonize, walk_repo
from .state import _locked, state_dir

INDEX_SCHEMA = 1
MAX_FILE_BYTES = 2_000_000
_WORD = re.compile(r"[A-Za-z0-9_$]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "code", "do",
    "for", "from", "how", "i", "if", "in", "into", "is", "it", "me", "of",
    "on", "or", "our", "please", "project", "the", "this", "to", "use", "we",
    "with", "you", "your", "fix", "implement", "add", "build", "create",
}
_CALL_STOP = {
    "if", "for", "while", "switch", "catch", "return", "function", "class",
    "def", "print", "len", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "super", "this", "new", "require", "import",
}
_JS_IMPORT = re.compile(
    r"(?:from\s+|require\s*\(|import\s*\()[\"']([^\"']+)[\"']",
    re.M,
)
_JS_SYMBOL = re.compile(
    r"\b(?:class|function|interface|type|enum)\s+([A-Za-z_$][\w$]*)|"
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\([^)]*\)|[\w$]+)\s*=>"
)
_JS_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")


def terms(text: str) -> list[str]:
    """Tokenise prose, paths and identifiers into stable lexical terms."""
    expanded = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " ").replace("/", " "))
    out: list[str] = []
    for match in _WORD.finditer(expanded):
        term = match.group(0).lower().strip("_$")
        if len(term) < 2 or term in _STOP:
            continue
        out.append(term)
    return out


def simhash(tokens: list[str]) -> int:
    """Deterministic 64-bit SimHash used as a cheap near-duplicate prefilter."""
    if not tokens:
        return 0
    weights = [0] * 64
    counts = Counter(tokens)
    for token, weight in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8", "replace"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += weight if value & (1 << bit) else -weight
    value = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            value |= 1 << bit
    return value


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


@dataclass
class IndexEntry:
    rel: str
    size: int
    mtime_ns: int
    digest: str
    outline: str
    term_counts: dict[str, int]
    imports: list[str]
    symbols: list[str]
    calls: list[str]
    simhash: int
    token_count: int


@dataclass
class ProjectIndex:
    root: Path
    entries: dict[str, IndexEntry]
    reused: int = 0
    rebuilt: int = 0
    removed: int = 0
    path: Path | None = None

    @property
    def scanned(self) -> int:
        return len(self.entries)


def index_path(root: Path) -> Path:
    identity = hashlib.sha256(str(root.resolve()).encode("utf-8", "replace")).hexdigest()
    return state_dir() / "indexes" / f"{identity}.json"


def _read_source(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _python_links(text: str) -> tuple[list[str], list[str], list[str]]:
    imports: set[str] = set()
    symbols: set[str] = set()
    calls: set[str] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * int(node.level or 0)
            if node.module:
                imports.add(prefix + node.module)
            else:
                imports.update(prefix + alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if len(node.name) >= 3:
                symbols.add(node.name.lower())
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and len(name) >= 3 and name.lower() not in _CALL_STOP:
                calls.add(name.lower())
    return sorted(imports), sorted(symbols), sorted(calls)


def _javascript_links(text: str) -> tuple[list[str], list[str], list[str]]:
    imports = sorted(set(_JS_IMPORT.findall(text)))
    symbols: set[str] = set()
    for match in _JS_SYMBOL.finditer(text):
        name = match.group(1) or match.group(2)
        if name and len(name) >= 3:
            symbols.add(name.lower())
    calls = {
        name.lower() for name in _JS_CALL.findall(text)
        if len(name) >= 3 and name.lower() not in _CALL_STOP
    }
    return imports, sorted(symbols), sorted(calls)


def _links(text: str, suffix: str) -> tuple[list[str], list[str], list[str]]:
    if suffix.lower() in {".py", ".pyi"}:
        return _python_links(text)
    if suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return _javascript_links(text)
    return [], [], []


def _analyse(path: Path, rel: str, text: str, stat: os.stat_result) -> IndexEntry:
    outline = skeletonize(text, path.suffix, line_numbers=True)
    counts = Counter(terms(text))
    counts.update(terms(outline))
    counts.update(terms(outline))
    for term in terms(rel):
        counts[term] += 3
    imports, symbols, calls = _links(text, path.suffix)
    source_terms = terms(text)
    return IndexEntry(
        rel=rel,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        digest=_digest(text),
        outline=outline,
        term_counts=dict(counts),
        imports=imports,
        symbols=symbols,
        calls=calls,
        simhash=simhash(source_terms),
        token_count=len(source_terms),
    )


def _load(path: Path) -> dict[str, IndexEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema") != INDEX_SCHEMA:
        return {}
    items = raw.get("entries")
    if not isinstance(items, dict):
        return {}
    out: dict[str, IndexEntry] = {}
    for rel, value in items.items():
        try:
            if isinstance(value, dict):
                out[rel] = IndexEntry(**value)
        except (TypeError, ValueError):
            continue
    return out


def _write(path: Path, root: Path, entries: dict[str, IndexEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "schema": INDEX_SCHEMA,
        "root": str(root.resolve()),
        "entries": {rel: asdict(entry) for rel, entry in sorted(entries.items())},
    }
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_index(
    root: Path,
    *,
    use_gitignore: bool = True,
    rebuild: bool = False,
) -> ProjectIndex:
    """Build/update the compact project index and report incremental reuse."""
    root = root.resolve()
    path = index_path(root)
    with _locked(path):
        cached = {} if rebuild else _load(path)
        entries: dict[str, IndexEntry] = {}
        reused = rebuilt = 0
        for source in walk_repo(root, use_gitignore=use_gitignore):
            try:
                stat = source.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES:
                continue
            rel = source.relative_to(root).as_posix()
            old = cached.get(rel)
            if old and old.size == stat.st_size and old.mtime_ns == stat.st_mtime_ns:
                entries[rel] = old
                reused += 1
                continue
            text = _read_source(source)
            if text is None:
                continue
            digest = _digest(text)
            if old and old.digest == digest:
                old.size = int(stat.st_size)
                old.mtime_ns = int(stat.st_mtime_ns)
                entries[rel] = old
                reused += 1
                continue
            entries[rel] = _analyse(source, rel, text, stat)
            rebuilt += 1
        removed = len(set(cached) - set(entries))
        if rebuild or rebuilt or removed or len(entries) != len(cached):
            _write(path, root, entries)
    return ProjectIndex(root, entries, reused=reused, rebuilt=rebuilt, removed=removed, path=path)


def _module_aliases(rel: str) -> set[str]:
    path = rel.replace("\\", "/")
    no_ext = re.sub(r"\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx)$", "", path)
    aliases = {no_ext, no_ext.replace("/", ".")}
    parts = no_ext.split("/")
    if len(parts) > 1:
        aliases.add("/".join(parts[1:]))
        aliases.add(".".join(parts[1:]))
    if parts[-1] == "__init__":
        parent = "/".join(parts[:-1])
        aliases.update({parent, parent.replace("/", ".")})
    aliases.add(parts[-1])
    return {a for a in aliases if a}


def dependency_graph(index: ProjectIndex) -> dict[str, set[str]]:
    """Resolve local Python/JS imports into a best-effort file dependency graph."""
    alias_map: dict[str, set[str]] = {}
    for rel in index.entries:
        for alias in _module_aliases(rel):
            alias_map.setdefault(alias, set()).add(rel)

    graph: dict[str, set[str]] = {rel: set() for rel in index.entries}
    for rel, entry in index.entries.items():
        base = Path(rel).parent
        for raw in entry.imports:
            candidates: set[str] = set()
            if raw.startswith(".") and not raw.startswith(".."):
                raw = raw[1:]
            if raw.startswith("./") or raw.startswith("../"):
                target = (base / raw).as_posix()
                target = re.sub(r"^\./", "", target)
                for suffix in ("", ".py", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js", "/__init__.py"):
                    probe = (target + suffix).replace("\\", "/")
                    if probe in index.entries:
                        candidates.add(probe)
            key = raw.strip(".").replace("/", ".")
            candidates.update(alias_map.get(key, set()))
            candidates.update(alias_map.get(key.replace(".", "/"), set()))
            candidates.discard(rel)
            graph[rel].update(candidates)
    return graph

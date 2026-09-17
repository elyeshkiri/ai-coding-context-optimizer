"""Incremental repository index and lightweight code relationship graph.

The index is deliberately dependency-free.  It extracts imports, declarations,
and call-like identifiers, persists records by content digest, and only reparses
files whose bytes changed.  Language-aware parsers can replace individual
extractors later without changing the on-disk format.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import ast
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .skeleton import walk_repo
from .security import inspect_path
from .syntax import JS_TS, symbols as syntax_symbols

INDEX_VERSION = 3
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
class SymbolRecord:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    parent: str | None = None
    calls: list[str] | None = None


@dataclass
class FileRecord:
    path: str
    digest: str
    size: int
    symbols: list[str]
    imports: list[str]
    calls: list[str]
    tokens: list[str]
    definitions: list[SymbolRecord] | None = None


@dataclass
class RepositoryIndex:
    root: Path
    records: dict[str, FileRecord]
    reparsed: int = 0
    reused: int = 0
    excluded: dict[str, str] | None = None
    # Lazily built, cached on first use. Each build_index() call constructs a
    # fresh RepositoryIndex, so caching on the instance is safe: `records`
    # never changes after construction, and nothing else can observe staleness.
    _caller_index: dict[str, list[tuple[str, SymbolRecord]]] | None = field(
        default=None, repr=False, compare=False
    )
    _test_file_signatures: list[tuple[str, str, set[str]]] | None = field(
        default=None, repr=False, compare=False
    )
    _neighbor_indexes: tuple[
        dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]
    ] | None = field(default=None, repr=False, compare=False)

    def find_symbols(self, name: str) -> list[tuple[str, SymbolRecord]]:
        needle = name.lower()
        exact: list[tuple[str, SymbolRecord]] = []
        partial: list[tuple[str, SymbolRecord]] = []
        for rel, record in self.records.items():
            for symbol in record.definitions or []:
                target = symbol.name.lower()
                if target == needle:
                    exact.append((rel, symbol))
                elif needle in target:
                    partial.append((rel, symbol))
        return sorted(exact or partial, key=lambda item: (item[0], item[1].start_line))

    def _callers_by_name(self) -> dict[str, list[tuple[str, SymbolRecord]]]:
        if self._caller_index is None:
            built: dict[str, list[tuple[str, SymbolRecord]]] = {}
            for rel, record in self.records.items():
                for symbol in record.definitions or []:
                    for call in {call.lower() for call in symbol.calls or []}:
                        built.setdefault(call, []).append((rel, symbol))
            self._caller_index = built
        return self._caller_index

    def symbol_callers(self, name: str) -> list[tuple[str, SymbolRecord]]:
        out = self._callers_by_name().get(name.lower(), [])
        return sorted(out, key=lambda item: (item[0], item[1].start_line))

    def test_file_signatures(self) -> list[tuple[str, str, set[str]]]:
        """(path, lowercased path, token set) for test/spec files, cached once.

        `record.tokens` is already lowercased by `_extract`, so the token set
        is reused as-is rather than rebuilt (with a redundant `.lower()` on
        every token) on each caller-impact lookup.
        """
        if self._test_file_signatures is None:
            self._test_file_signatures = [
                (rel, rel.lower(), set(record.tokens))
                for rel, record in self.records.items()
                if "test" in rel.lower() or "spec" in rel.lower()
            ]
        return self._test_file_signatures

    def _build_neighbor_indexes(
        self,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
        # Reverse indexes so neighbors() can look candidates up instead of
        # scanning every other file. Each mirrors one branch of the original
        # per-pair comparison exactly (including its "check the split key
        # against the already-transformed set" quirk), so results are
        # unchanged -- only how candidates are found.
        imported_by_index: dict[str, set[str]] = {}
        stem_index: dict[str, set[str]] = {}
        call_symbol_index: dict[str, set[str]] = {}
        symbol_def_index: dict[str, set[str]] = {}
        for other_rel, other in self.records.items():
            stem_index.setdefault(Path(other_rel).stem.lower(), set()).add(other_rel)
            import_keys = {Path(value).name.lower() for value in other.imports}
            for key in import_keys | {key.split(".")[-1] for key in import_keys}:
                imported_by_index.setdefault(key, set()).add(other_rel)
            for key in {call.split(".")[-1].lower() for call in other.calls}:
                call_symbol_index.setdefault(key, set()).add(other_rel)
            for key in {s.lower() for s in other.symbols}:
                symbol_def_index.setdefault(key, set()).add(other_rel)
        return imported_by_index, stem_index, call_symbol_index, symbol_def_index

    def neighbors(self, rel: str) -> list[tuple[str, str]]:
        """Return related files and the edge that connected them."""
        source = self.records.get(rel)
        if source is None:
            return []
        if self._neighbor_indexes is None:
            self._neighbor_indexes = self._build_neighbor_indexes()
        imported_by_index, stem_index, call_symbol_index, symbol_def_index = self._neighbor_indexes

        source_stem = Path(rel).stem.lower()
        source_symbols = {s.lower() for s in source.symbols}
        reverse_imports = {Path(value).name.lower() for value in source.imports}
        source_calls = {call.split(".")[-1].lower() for call in source.calls}

        imported_by = imported_by_index.get(source_stem, set()) - {rel}
        imports_candidates: set[str] = set()
        for key in reverse_imports | {key.split(".")[-1] for key in reverse_imports}:
            imports_candidates |= stem_index.get(key, set())
        imports_candidates -= {rel}
        calls_symbol_candidates: set[str] = set()
        for symbol in source_symbols:
            calls_symbol_candidates |= call_symbol_index.get(symbol, set())
        calls_symbol_candidates -= {rel}
        calls_candidates: set[str] = set()
        for call in source_calls:
            calls_candidates |= symbol_def_index.get(call, set())
        calls_candidates -= {rel}

        out: dict[str, str] = {}
        for other_rel in imported_by | imports_candidates | calls_symbol_candidates | calls_candidates:
            if other_rel in imported_by:
                out[other_rel] = "imported-by"
            elif other_rel in imports_candidates:
                out[other_rel] = "imports"
            elif other_rel in calls_symbol_candidates:
                out[other_rel] = "calls-symbol"
            elif other_rel in calls_candidates:
                out[other_rel] = "calls"
        return sorted(out.items())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _python_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    try:
        args = ast.unparse(node.args)
        returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix} {node.name}({args}){returns}"
    except (ValueError, TypeError):
        return f"{prefix} {node.name}(...)"


def _extract_python(text: str) -> tuple[set[str], set[str], set[str], list[SymbolRecord]]:
    symbols: set[str] = set()
    imports: set[str] = set()
    calls: set[str] = set()
    definitions: list[SymbolRecord] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports, calls, definitions
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
            local_calls = {
                name for child in ast.walk(node)
                if isinstance(child, ast.Call) and (name := _python_name(child.func))
            }
            parent = None
            for candidate in ast.walk(tree):
                if isinstance(candidate, ast.ClassDef) and node in candidate.body:
                    parent = candidate.name
                    break
            definitions.append(SymbolRecord(
                name=node.name,
                kind="class" if isinstance(node, ast.ClassDef) else "function",
                start_line=int(getattr(node, "lineno", 1)),
                end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                signature=_python_signature(node),
                parent=parent,
                calls=sorted(local_calls),
            ))
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
    return symbols, imports, calls, definitions


def _extract_generic_definitions(text: str) -> list[SymbolRecord]:
    lines = text.splitlines()
    found: list[SymbolRecord] = []
    for match in _DECL.finditer(text):
        name = match.group(1) or match.group(2)
        start = text.count("\n", 0, match.start()) + 1
        signature = lines[start - 1].strip() if start <= len(lines) else name
        found.append(SymbolRecord(name, "symbol", start, start, signature[:300], calls=[]))
    return found


def _extract_javascript_definitions(text: str, suffix: str) -> list[SymbolRecord]:
    """Return Tree-sitter-backed JS/TS ranges, with a conservative fallback."""
    try:
        parsed = syntax_symbols(text, suffix)
    except (ImportError, ValueError, OSError):
        return _extract_generic_definitions(text)
    lines = text.splitlines()
    out = []
    for symbol in parsed:
        body = "\n".join(lines[max(0, symbol.start - 1):symbol.end])
        calls = sorted({match.group(1).split(".")[-1] for match in _CALL.finditer(body)} - _CALL_STOP)
        parent = symbol.qualified.rsplit(".", 1)[0] if "." in symbol.qualified else None
        out.append(SymbolRecord(
            symbol.name, "symbol", symbol.start, symbol.end,
            symbol.signature[:500], parent, calls,
        ))
    return out


def _extract(text: str, suffix: str) -> tuple[list[str], list[str], list[str], list[str], list[SymbolRecord]]:
    if suffix.lower() in {".py", ".pyi"}:
        symbols, imports, calls, definitions = _extract_python(text)
    else:
        symbols = {a or b for a, b in _DECL.findall(text)}
        imports = {next(value for value in groups if value) for groups in _IMPORT.findall(text)}
        calls = {match.group(1).split(".")[-1] for match in _CALL.finditer(text)} - _CALL_STOP
        definitions = (
            _extract_javascript_definitions(text, suffix.lower())
            if suffix.lower() in JS_TS else _extract_generic_definitions(text)
        )
    tokens = sorted({value.lower() for value in _IDENT.findall(text) if len(value) > 2})
    return sorted(symbols), sorted(imports), sorted(calls), tokens, definitions


def _default_cache(root: Path) -> Path:
    state = os.environ.get("TOKEN_SAVER_STATE_DIR")
    base = Path(state).expanduser() if state else Path.home() / ".claude" / "token-saver"
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return base / "indexes" / f"{key}.json"


def _load(path: Path) -> dict[str, FileRecord]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != INDEX_VERSION:
            return {}
        raw_records = payload.get("records", {})
        if not isinstance(raw_records, dict):
            return {}
        records = {}
        for key, value in raw_records.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            value = dict(value)
            raw_definitions = value.get("definitions") or []
            if not isinstance(raw_definitions, list):
                continue
            value["definitions"] = [
                item if isinstance(item, SymbolRecord) else SymbolRecord(**item)
                for item in raw_definitions if isinstance(item, (dict, SymbolRecord))
            ]
            records[key] = FileRecord(**value)
        return records
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _save(path: Path, records: dict[str, FileRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"version": INDEX_VERSION, "records": {key: asdict(value) for key, value in records.items()}}
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
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
    excluded: dict[str, str] = {}
    reparsed = reused = 0
    for path in walk_repo(root, use_gitignore=use_gitignore):
        decision = inspect_path(root, path)
        if not decision.allowed:
            try:
                excluded[path.relative_to(root).as_posix()] = decision.reason
            except ValueError:
                excluded[str(path)] = decision.reason
            continue
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
        symbols, imports, calls, tokens, definitions = _extract(text, path.suffix)
        records[rel] = FileRecord(
            rel, digest, len(text.encode()), symbols, imports, calls, tokens, definitions
        )
        reparsed += 1
    if persist:
        _save(target, records)
    return RepositoryIndex(root, records, reparsed, reused, excluded)


def record_for_text(rel: str, text: str) -> FileRecord:
    """Analyze one in-memory source using the same versioned index extractors."""
    symbols, imports, calls, tokens, definitions = _extract(text, Path(rel).suffix)
    return FileRecord(
        rel, _digest(text), len(text.encode()), symbols, imports, calls, tokens, definitions
    )


def similarity(left: FileRecord, right: FileRecord) -> float:
    """Jaccard similarity over identifiers; robust to whitespace/comment churn."""
    a, b = set(left.tokens), set(right.tokens)
    return len(a & b) / len(a | b) if a and b else 0.0

"""Incremental repository index and lightweight code relationship graph.

The index persists both structural relationships and retrieval-ready lexical
statistics. Warm refreshes reuse records by file metadata, so unchanged source
files are not reopened merely to answer another agent query.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import ast
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .lexical import document_counts
from .security import ENV_TEMPLATE_NAMES, inspect_path
from .semantic_ts import extract_module_refs, resolve_module_path
from .skeleton import skeletonize, walk_repo
from .syntax import JS_TS, STRUCTURED_EXTRA, structured_imports, symbols as syntax_symbols

INDEX_VERSION = 7
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
_SQL_TABLE = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
    r"[\"'`]?([A-Za-z_][\w]*)[\"'`]?", re.I,
)
_SQL_REFERENCES = re.compile(r"\bREFERENCES\s+[\"'`]?([A-Za-z_][\w]*)[\"'`]?", re.I)
_ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_YAML_TOP_KEY = re.compile(r"^(\w[\w.-]*)\s*:")
_YAML_JOB_KEY = re.compile(r"^  ([\w.-]+)\s*:")


@dataclass
class SymbolRecord:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    parent: str | None = None
    calls: list[str] | None = None
    qualified: str | None = None


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
    mtime_ns: int = 0
    outline: str = ""
    term_counts: dict[str, int] | None = None
    semantic_refs: list[dict[str, str]] | None = None

    @property
    def document_length(self) -> int:
        return sum((self.term_counts or {}).values())


@dataclass
class RepositoryIndex:
    root: Path
    records: dict[str, FileRecord]
    reparsed: int = 0
    reused: int = 0
    excluded: dict[str, str] | None = None
    _caller_index: dict[str, list[tuple[str, SymbolRecord]]] | None = field(
        default=None, repr=False, compare=False
    )
    _test_file_signatures: list[tuple[str, str, set[str]]] | None = field(
        default=None, repr=False, compare=False
    )
    _neighbor_indexes: tuple[
        dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]
    ] | None = field(default=None, repr=False, compare=False)
    _semantic_neighbors: dict[str, list[tuple[str, str]]] | None = field(
        default=None, repr=False, compare=False
    )

    def find_symbols(self, name: str) -> list[tuple[str, SymbolRecord]]:
        needle = name.lower()
        qualified_exact: list[tuple[str, SymbolRecord]] = []
        exact: list[tuple[str, SymbolRecord]] = []
        partial: list[tuple[str, SymbolRecord]] = []
        for rel, record in self.records.items():
            for symbol in record.definitions or []:
                qualified = (symbol.qualified or symbol.name).lower()
                target = symbol.name.lower()
                if qualified == needle:
                    qualified_exact.append((rel, symbol))
                elif target == needle:
                    exact.append((rel, symbol))
                elif needle in qualified or needle in target:
                    partial.append((rel, symbol))
        return sorted(
            qualified_exact or exact or partial,
            key=lambda item: (item[0], item[1].start_line),
        )

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

    def _build_semantic_neighbors(self) -> dict[str, list[tuple[str, str]]]:
        known = self.records.keys()
        out: dict[str, list[tuple[str, str]]] = {}
        for rel, record in self.records.items():
            targets: dict[str, str] = {}
            for ref in record.semantic_refs or []:
                module = ref.get("module", "")
                target = resolve_module_path(rel, module, known)
                if target is None or target == rel:
                    continue
                kind = ref.get("kind", "semantic-call")
                # A concrete alias-resolved call carries more information than
                # a broad re-export relation when both point at the same file.
                if target not in targets or kind == "semantic-call":
                    targets[target] = kind
            if targets:
                out[rel] = sorted(targets.items())
        return out

    def neighbors(self, rel: str) -> list[tuple[str, str]]:
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

        if self._semantic_neighbors is None:
            self._semantic_neighbors = self._build_semantic_neighbors()
        for target, edge in self._semantic_neighbors.get(rel, []):
            out[target] = edge
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
                qualified=f"{parent}.{node.name}" if parent else node.name,
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
        found.append(SymbolRecord(
            name, "symbol", start, start, signature[:300],
            calls=[], qualified=name,
        ))
    return found


def _extract_javascript_definitions(text: str, suffix: str) -> list[SymbolRecord]:
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
            symbol.name, symbol.kind, symbol.start, symbol.end,
            symbol.signature[:500], parent,
            list(symbol.calls) if symbol.calls else calls,
            symbol.qualified,
        ))
    return out


def _extract_sql(text: str) -> tuple[set[str], set[str], list[SymbolRecord]]:
    symbols: set[str] = set()
    definitions: list[SymbolRecord] = []
    lines = text.splitlines()
    for match in _SQL_TABLE.finditer(text):
        name = match.group(1)
        symbols.add(name)
        start = text.count("\n", 0, match.start()) + 1
        signature = lines[start - 1].strip()[:300] if start <= len(lines) else name
        referenced = sorted({ref for ref in _SQL_REFERENCES.findall(
            text[match.end():match.end() + 4000]
        ) if ref.lower() != name.lower()})
        definitions.append(SymbolRecord(name, "table", start, start, signature, calls=referenced))
    calls = set(_SQL_REFERENCES.findall(text))
    return symbols, calls, definitions


def _extract_package_json(text: str) -> tuple[set[str], set[str], list[SymbolRecord]]:
    symbols: set[str] = set()
    imports: set[str] = set()
    definitions: list[SymbolRecord] = []
    try:
        payload = json.loads(text)
    except ValueError:
        return symbols, imports, definitions
    if not isinstance(payload, dict):
        return symbols, imports, definitions
    scripts = payload.get("scripts")
    if isinstance(scripts, dict):
        for name, command in scripts.items():
            if not isinstance(name, str) or not isinstance(command, str):
                continue
            symbols.add(name)
            needle = f'"{name}"'
            idx = text.find(needle)
            start = text.count("\n", 0, idx) + 1 if idx >= 0 else 1
            definitions.append(SymbolRecord(name, "script", start, start, command[:300]))
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = payload.get(key)
        if isinstance(deps, dict):
            imports.update(name for name in deps if isinstance(name, str))
    return symbols, imports, definitions


def _extract_yaml_ci_jobs(text: str) -> tuple[set[str], list[SymbolRecord]]:
    symbols: set[str] = set()
    definitions: list[SymbolRecord] = []
    lines = text.splitlines()
    in_jobs = False
    for i, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _YAML_TOP_KEY.match(line):
            in_jobs = line.split(":", 1)[0].strip() == "jobs"
            continue
        if in_jobs:
            match = _YAML_JOB_KEY.match(line)
            if match:
                name = match.group(1)
                symbols.add(name)
                definitions.append(SymbolRecord(name, "ci-job", i, i, line.strip()[:300]))
    return symbols, definitions


def _extract_env_vars(text: str) -> tuple[set[str], list[SymbolRecord]]:
    symbols: set[str] = set()
    definitions: list[SymbolRecord] = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match:
            name = match.group(1)
            symbols.add(name)
            definitions.append(SymbolRecord(name, "env-var", i, i, stripped[:300]))
    return symbols, definitions


def _extract(
    text: str, suffix: str, rel: str = "",
) -> tuple[list[str], list[str], list[str], list[str], list[SymbolRecord]]:
    name = Path(rel).name if rel else ""
    if suffix.lower() in {".py", ".pyi"}:
        symbols, imports, calls, definitions = _extract_python(text)
    elif suffix.lower() == ".sql":
        symbols, calls, definitions = _extract_sql(text)
        imports = set()
    elif name == "package.json":
        symbols, imports, definitions = _extract_package_json(text)
        calls = set()
    elif suffix.lower() in {".yaml", ".yml"} and ".github/workflows/" in rel.replace("\\", "/"):
        symbols, definitions = _extract_yaml_ci_jobs(text)
        imports, calls = set(), set()
    elif name in ENV_TEMPLATE_NAMES:
        symbols, definitions = _extract_env_vars(text)
        imports, calls = set(), set()
    elif suffix.lower() in {".json", ".yaml", ".yml"}:
        symbols, imports, calls, definitions = set(), set(), set(), []
    else:
        lowered = suffix.lower()
        if lowered in STRUCTURED_EXTRA:
            definitions = _extract_javascript_definitions(text, lowered)
            symbols = {definition.name for definition in definitions}
            imports = structured_imports(text, lowered)
            calls = {
                call
                for definition in definitions
                for call in (definition.calls or [])
            }
        else:
            imports = {next(value for value in groups if value) for groups in _IMPORT.findall(text)}
            calls = {match.group(1).split(".")[-1] for match in _CALL.finditer(text)} - _CALL_STOP
            if lowered in JS_TS:
                definitions = _extract_javascript_definitions(text, lowered)
                symbols = {definition.name for definition in definitions}
            else:
                symbols = {a or b for a, b in _DECL.findall(text)}
                definitions = _extract_generic_definitions(text)
    tokens = sorted({value.lower() for value in _IDENT.findall(text) if len(value) > 2})
    return sorted(symbols), sorted(imports), sorted(calls), tokens, definitions


def _outline(text: str, suffix: str) -> str:
    try:
        return skeletonize(text, suffix, line_numbers=True)
    except (SyntaxError, ValueError):
        return ""


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
        records: dict[str, FileRecord] = {}
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
            raw_counts = value.get("term_counts")
            if raw_counts is not None and not isinstance(raw_counts, dict):
                value["term_counts"] = None
            raw_refs = value.get("semantic_refs")
            if raw_refs is not None and not isinstance(raw_refs, list):
                value["semantic_refs"] = None
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


def _record(rel: str, text: str, suffix: str, *, size: int, mtime_ns: int) -> FileRecord:
    symbols, imports, calls, tokens, definitions = _extract(text, suffix, rel)
    outline = _outline(text, suffix)
    return FileRecord(
        rel, _digest(text), size, symbols, imports, calls, tokens, definitions,
        mtime_ns=mtime_ns, outline=outline,
        term_counts=document_counts(text, outline, rel),
        semantic_refs=extract_module_refs(text) if suffix.lower() in JS_TS else [],
    )


def build_index(
    root: Path, *, use_gitignore: bool = True, cache_path: Path | None = None,
    persist: bool = True,
) -> RepositoryIndex:
    root = root.resolve()
    target = cache_path or _default_cache(root)
    resolved_target = target.resolve()
    old = _load(target) if persist else {}
    records: dict[str, FileRecord] = {}
    excluded: dict[str, str] = {}
    reparsed = reused = 0

    for path in walk_repo(root, use_gitignore=use_gitignore):
        if path.resolve() == resolved_target:
            continue
        decision = inspect_path(root, path)
        if not decision.allowed:
            try:
                excluded[path.relative_to(root).as_posix()] = decision.reason
            except ValueError:
                excluded[str(path)] = decision.reason
            continue
        try:
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
        except OSError:
            continue

        previous = old.get(rel)
        if (
            previous is not None
            and previous.size == stat.st_size
            and previous.mtime_ns == stat.st_mtime_ns
            and previous.term_counts is not None
        ):
            records[rel] = previous
            reused += 1
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        digest = _digest(text)
        if previous is not None and previous.digest == digest and previous.term_counts is not None:
            records[rel] = replace(previous, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            reused += 1
            continue

        records[rel] = _record(
            rel, text, path.suffix, size=stat.st_size, mtime_ns=stat.st_mtime_ns
        )
        reparsed += 1

    if persist:
        _save(target, records)
    return RepositoryIndex(root, records, reparsed, reused, excluded)


def record_for_text(rel: str, text: str) -> FileRecord:
    """Analyze one in-memory source using the same versioned index extractors."""
    return _record(rel, text, Path(rel).suffix, size=len(text.encode()), mtime_ns=0)


def similarity(left: FileRecord, right: FileRecord) -> float:
    """Jaccard similarity over identifiers; robust to whitespace/comment churn."""
    a, b = set(left.tokens), set(right.tokens)
    return len(a & b) / len(a | b) if a and b else 0.0

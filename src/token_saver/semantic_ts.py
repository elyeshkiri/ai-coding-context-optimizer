"""JS/TS semantic relationship helpers.

The lightweight parser resolves statically-decidable relative imports and
re-exports without external tooling. Optionally, Token Saver can ask a
repository's already-installed TypeScript compiler to resolve call/type/import
relationships to concrete files. Nothing is downloaded and the lightweight
resolver remains the deterministic fallback.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from collections.abc import Iterable

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
_MEMBER = re.compile(r"\b([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\b")
_JS_TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _named_items(raw: str, *, export: bool = False) -> list[tuple[str, str]]:
    """Return (remote, local/public) bindings from a ``{ ... }`` clause."""
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


def _identifier_used(text: str, identifier: str) -> bool:
    """Return whether an imported binding occurs outside its declaration."""
    return len(re.findall(rf"\b{re.escape(identifier)}\b", text)) > 1


def extract_module_refs(text: str) -> list[dict[str, str]]:
    """Extract imported symbol uses and re-exports from JS/TS source."""
    calls = {match.group(1) for match in _CALL.finditer(text)}
    bare_calls = {value.split(".")[-1] for value in calls}
    refs: list[dict[str, str]] = []

    for match in _NAMED_IMPORT.finditer(text):
        module = match.group("module")
        for remote, local in _named_items(match.group("items")):
            called = local in bare_calls
            if called or _identifier_used(text, local):
                refs.append({
                    "module": module, "symbol": remote, "local": local,
                    "kind": "semantic-call" if called else "semantic-ref",
                })

    for match in _DEFAULT_IMPORT.finditer(text):
        local = match.group("local")
        called = local in bare_calls
        if called or _identifier_used(text, local):
            refs.append({
                "module": match.group("module"), "symbol": "default", "local": local,
                "kind": "semantic-call" if called else "semantic-ref",
            })

    for match in _NAMESPACE_IMPORT.finditer(text):
        local = match.group("local")
        module = match.group("module")
        members = {
            member for owner, member in _MEMBER.findall(text) if owner == local
        }
        for member in members:
            full = f"{local}.{member}"
            receiver_called = any(
                call == full or call.startswith(full + ".") for call in calls
            )
            refs.append({
                "module": module,
                "symbol": member,
                "local": full,
                "kind": "semantic-call" if receiver_called else "semantic-ref",
            })

    for match in _REQUIRE_DESTRUCTURE.finditer(text):
        module = match.group("module")
        for remote, local in _named_items(match.group("items")):
            called = local in bare_calls
            if called or _identifier_used(text, local):
                refs.append({
                    "module": module, "symbol": remote, "local": local,
                    "kind": "semantic-call" if called else "semantic-ref",
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
    candidates.extend(f"{base}/index{suffix}" for suffix in suffixes[1:])
    return next((candidate for candidate in candidates if candidate in known), None)


_NODE_SCRIPT = r'''
const path = require("path");
const root = path.resolve(process.argv[1]);
let ts;
try {
  const resolved = require.resolve("typescript", { paths: [root] });
  ts = require(resolved);
} catch (err) {
  process.stderr.write("TOKEN_SAVER_TYPESCRIPT_NOT_INSTALLED\n");
  process.exit(3);
}
const configPath = ts.findConfigFile(root, ts.sys.fileExists, "tsconfig.json");
if (!configPath) {
  process.stderr.write("TOKEN_SAVER_TSCONFIG_NOT_FOUND\n");
  process.exit(4);
}
const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
if (configFile.error) {
  process.stderr.write("TOKEN_SAVER_TSCONFIG_INVALID\n");
  process.exit(5);
}
const parsed = ts.parseJsonConfigFileContent(configFile.config, ts.sys, path.dirname(configPath));
if (parsed.errors && parsed.errors.length) {
  process.stderr.write("TOKEN_SAVER_TSCONFIG_INVALID\n");
  process.exit(5);
}
const program = ts.createProgram({ rootNames: parsed.fileNames, options: parsed.options });
const checker = program.getTypeChecker();
const edges = Object.create(null);
function rel(fileName) {
  return path.relative(root, path.resolve(fileName)).split(path.sep).join("/");
}
function internal(sf) {
  const r = rel(sf.fileName);
  return r && !r.startsWith("../") && !path.isAbsolute(r) &&
    !r.includes("/node_modules/") && !r.startsWith("node_modules/");
}
function add(from, target) {
  if (!target || target === from || target.startsWith("../") || path.isAbsolute(target)) return;
  if (!edges[from]) edges[from] = new Set();
  edges[from].add(target);
}
function addSymbol(from, symbol) {
  if (!symbol) return;
  try {
    if (symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
  } catch (_) {}
  for (const decl of symbol.declarations || []) {
    const sf = decl.getSourceFile && decl.getSourceFile();
    if (sf && internal(sf)) add(from, rel(sf.fileName));
  }
}
for (const sf of program.getSourceFiles()) {
  if (!internal(sf)) continue;
  const from = rel(sf.fileName);
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      addSymbol(from, checker.getSymbolAtLocation(node.moduleSpecifier));
    } else if (ts.isImportEqualsDeclaration(node)) {
      addSymbol(from, checker.getSymbolAtLocation(node.name));
    } else if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      const expr = node.expression;
      const target = ts.isPropertyAccessExpression(expr) ? expr.name : expr;
      addSymbol(from, checker.getSymbolAtLocation(target));
    } else if (ts.isTypeReferenceNode(node)) {
      addSymbol(from, checker.getSymbolAtLocation(node.typeName));
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
}
const out = {};
for (const [key, values] of Object.entries(edges)) out[key] = Array.from(values).sort();
process.stdout.write(JSON.stringify(out));
'''


def semantic_requested(value: bool | None = None) -> bool:
    """Return whether compiler-backed semantic resolution is requested."""
    if value is not None:
        return value
    return os.environ.get("TOKEN_SAVER_TS_SEMANTIC", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def resolve_typescript_edges(
    root: Path,
    *,
    timeout: float = 20.0,
    strict: bool = False,
) -> dict[str, list[str]]:
    """Resolve TS/JS relationships with the repository's local TypeScript compiler.

    Returns an empty mapping when Node, TypeScript, or tsconfig is unavailable,
    unless ``strict`` is requested. The function never installs dependencies.
    """
    root = root.resolve()
    node = shutil.which("node")
    if node is None:
        if strict:
            raise RuntimeError("TypeScript semantic resolution requires Node.js")
        return {}
    try:
        proc = subprocess.run(
            [node, "-e", _NODE_SCRIPT, str(root)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise RuntimeError(
                f"TypeScript semantic resolution failed: {type(exc).__name__}"
            ) from exc
        return {}
    if proc.returncode != 0:
        if strict:
            detail = proc.stderr.strip() or f"node exited {proc.returncode}"
            raise RuntimeError(f"TypeScript semantic resolution failed: {detail}")
        return {}
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        if strict:
            raise RuntimeError("TypeScript semantic resolver returned invalid JSON") from exc
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, list[str]] = {}
    for source, targets in payload.items():
        if not isinstance(source, str) or not isinstance(targets, list):
            continue
        clean = sorted({
            target.replace("\\", "/")
            for target in targets
            if isinstance(target, str) and target != source
        })
        if clean:
            out[source.replace("\\", "/")] = clean
    return out


def _relative_module(source_rel: str, target_rel: str) -> str:
    source_dir = Path(source_rel).parent
    source_parts = list(source_dir.parts)
    target = Path(target_rel)
    target_parts = list(target.parts)
    common = 0
    while (
        common < len(source_parts)
        and common < len(target_parts)
        and source_parts[common] == target_parts[common]
    ):
        common += 1
    parts = [".."] * (len(source_parts) - common) + target_parts[common:]
    module = "/".join(parts) or target.name
    suffix = Path(module).suffix.lower()
    if suffix in _JS_TS_EXTENSIONS:
        module = module[: -len(suffix)]
    if module.endswith("/index"):
        module = module[:-6]
    if not module.startswith("."):
        module = "./" + module
    return module


def enrich_index_with_typescript(
    index: Any,
    *,
    enabled: bool | None = None,
    strict: bool = False,
    timeout: float = 20.0,
) -> int:
    """Overlay compiler-resolved edges onto an existing RepositoryIndex.

    Edges are encoded using the existing semantic-ref representation, so the
    current graph/closure/impact machinery remains single-sourced. Returns the
    number of compiler edges added.
    """
    if not semantic_requested(enabled):
        return 0
    edges = resolve_typescript_edges(index.root, timeout=timeout, strict=strict)
    added = 0
    for source, targets in edges.items():
        record = index.records.get(source)
        if record is None:
            continue
        refs = list(record.semantic_refs or [])
        seen = {
            (ref.get("module"), ref.get("kind"))
            for ref in refs if isinstance(ref, dict)
        }
        for target in targets:
            if target not in index.records or target == source:
                continue
            module = _relative_module(source, target)
            key = (module, "semantic-call")
            if key in seen:
                continue
            refs.append({
                "module": module,
                "symbol": "*",
                "local": "*",
                "kind": "semantic-call",
            })
            seen.add(key)
            added += 1
        record.semantic_refs = refs
    # The graph caches semantic resolution lazily. Clear it if a caller already
    # asked for neighbors before enrichment.
    if hasattr(index, "_semantic_neighbors"):
        index._semantic_neighbors = None
    return added

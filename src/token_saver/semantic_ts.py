"""Optional TypeScript compiler-API relationship resolver.

The deterministic lexical graph remains the default/fallback.  When enabled,
this module asks the repository's own installed `typescript` package to resolve
imports, re-exports and call targets to concrete source files.  Nothing is
downloaded and no global npm package is required.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


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
  return r && !r.startsWith("../") && !path.isAbsolute(r) && !r.includes("/node_modules/") && !r.startsWith("node_modules/");
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


def resolve_typescript_edges(
    root: Path,
    *,
    timeout: float = 20.0,
    strict: bool = False,
) -> dict[str, list[str]]:
    """Resolve TS/JS source relationships with the local TypeScript compiler.

    Returns an empty mapping when Node, TypeScript, or tsconfig is unavailable,
    unless ``strict`` is requested.  The function never installs dependencies.
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
            raise RuntimeError(f"TypeScript semantic resolution failed: {type(exc).__name__}") from exc
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
        clean = sorted({target for target in targets if isinstance(target, str) and target != source})
        if clean:
            out[source.replace("\\", "/")] = [target.replace("\\", "/") for target in clean]
    return out

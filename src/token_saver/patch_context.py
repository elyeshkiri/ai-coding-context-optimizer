"""Patch-aware context construction and deterministic review signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import subprocess

from .impact import analyze_impact
from .pack import build_context_pack
from .repo_index import RepositoryIndex, build_index, record_for_text
from .security import inspect_path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class ChangedPath:
    path: str
    added_lines: tuple[int, ...]
    status: str = "modified"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"git command failed: {type(exc).__name__}") from exc


def collect_patch(root: Path, *, base: str = "HEAD", staged: bool = False) -> list[ChangedPath]:
    args = ["diff", "--unified=0", "--no-color"]
    if staged:
        args.append("--cached")
    else:
        args.append(base)
    proc = _git(root, *args)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or "unable to read git diff")
    changes: dict[str, set[int]] = {}
    current: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changes.setdefault(current, set())
            continue
        match = _HUNK.match(line)
        if current and match:
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            changes[current].update(range(start, start + count))
    status_proc = _git(root, "diff", "--name-status", *( ["--cached"] if staged else [base] ))
    statuses = {}
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                statuses[parts[-1]] = parts[0]
                changes.setdefault(parts[-1], set())
    return [
        ChangedPath(path, tuple(sorted(lines)), statuses.get(path, "M"))
        for path, lines in sorted(changes.items())
    ]


def changed_symbols(index: RepositoryIndex, change: ChangedPath) -> list[str]:
    record = index.records.get(change.path)
    if record is None:
        return []
    lines = set(change.added_lines)
    return [
        symbol.name for symbol in record.definitions or []
        if not lines or any(symbol.start_line <= line <= symbol.end_line for line in lines)
    ]


def _old_signatures(root: Path, base: str, path: str) -> dict[str, str]:
    proc = _git(root, "show", f"{base}:{path}")
    if proc.returncode != 0:
        return {}
    record = record_for_text(path, proc.stdout)
    return {_symbol_key(symbol): symbol.signature for symbol in record.definitions or []}


def _symbol_key(symbol) -> str:
    return f"{symbol.parent}.{symbol.name}" if symbol.parent else symbol.name


def review_patch(root: Path, *, base: str = "HEAD", staged: bool = False) -> dict:
    index = build_index(root)
    changes = collect_patch(root, base=base, staged=staged)
    files = []
    all_impacts = {}
    warnings = []
    source_changed = False
    tests_changed = False
    for change in changes:
        symbols = changed_symbols(index, change)
        path_lower = change.path.lower()
        is_test = "test" in path_lower or "spec" in path_lower
        tests_changed = tests_changed or is_test
        source_changed = source_changed or (not is_test and change.path in index.records)
        decision = inspect_path(root, root / change.path)
        if not decision.allowed:
            warnings.append({"code": "sensitive-path", "path": change.path, "detail": decision.reason})
        old = _old_signatures(root, base, change.path)
        current = index.records.get(change.path)
        new = {
            _symbol_key(symbol): symbol.signature for symbol in current.definitions or []
        } if current else {}
        signature_changes = sorted(name for name in old.keys() & new.keys() if old[name] != new[name])
        removed = sorted(old.keys() - new.keys())
        if signature_changes or removed:
            warnings.append({
                "code": "public-api-change", "path": change.path,
                "symbols": signature_changes + removed,
            })
        targets = symbols or ([change.path] if change.path in index.records else [])
        impacts = []
        for target in targets[:10]:
            try:
                report = analyze_impact(root, target, index=index)
            except ValueError:
                continue
            impacts.extend(asdict(item) for item in report.affected[:20])
        all_impacts[change.path] = impacts
        files.append({**asdict(change), "symbols": symbols, "signature_changes": signature_changes, "removed_symbols": removed})
    if source_changed and not tests_changed:
        warnings.append({"code": "tests-not-changed", "detail": "source changed without a test-file change"})
    return {"base": base, "staged": staged, "files": files, "impacts": all_impacts, "warnings": warnings}


def build_diff_context(
    root: Path, *, base: str = "HEAD", staged: bool = False,
    max_tokens: int = 6000,
) -> dict:
    review = review_patch(root, base=base, staged=staged)
    parts = []
    for item in review["files"]:
        parts.extend([item["path"], *item["symbols"]])
    query = "review changed behavior and regressions " + " ".join(parts)
    pack = build_context_pack(root, query, max_tokens=max_tokens, changed_boost=True)
    return {
        "review": review,
        "context": pack.text,
        "estimated_tokens": pack.estimated_tokens,
        "selected_files": pack.selected_files,
        "selected_symbols": pack.selected_symbols,
        "closure_files": pack.closure_files,
    }

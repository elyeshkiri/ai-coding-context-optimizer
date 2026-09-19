"""Patch-aware context construction and deterministic review signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import subprocess
import time

from .impact import analyze_impact
from .pack import ContextPack, build_context_pack
from .repo_index import RepositoryIndex, build_index, record_for_text
from .security import inspect_path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Each analyze_impact() call scans the whole repository index, and cost is
# not uniform: a common name (e.g. a Next.js route's "GET"/"POST" export)
# can fan out to thousands of unrelated matches and take tens of seconds,
# while most calls take well under a second. A raw call-count cap doesn't
# bound wall time under that variance, so bound elapsed time directly. A
# diff touching hundreds of files (e.g. a merge commit) degrades to partial
# impact data instead of taking minutes.
_MAX_IMPACT_SECONDS = 10.0


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
    impact_deadline = time.monotonic() + _MAX_IMPACT_SECONDS
    impact_budget_exceeded = False
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
            if time.monotonic() >= impact_deadline:
                impact_budget_exceeded = True
                break
            try:
                report = analyze_impact(root, target, index=index)
            except ValueError:
                continue
            impacts.extend(asdict(item) for item in report.affected[:20])
        all_impacts[change.path] = impacts
        files.append({**asdict(change), "symbols": symbols, "signature_changes": signature_changes, "removed_symbols": removed})
    if source_changed and not tests_changed:
        warnings.append({"code": "tests-not-changed", "detail": "source changed without a test-file change"})
    if impact_budget_exceeded:
        warnings.append({
            "code": "impact-analysis-truncated",
            "detail": f"diff is large; impact analysis stopped after {_MAX_IMPACT_SECONDS:g}s budget",
        })
    return {"base": base, "staged": staged, "files": files, "impacts": all_impacts, "warnings": warnings}


def _evidence_category(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".sql") or "migrations/" in lower or "/drizzle/" in lower or lower.startswith("drizzle/"):
        return "database"
    if ".github/workflows/" in lower:
        return "ci"
    if "test" in lower or "spec" in lower:
        return "tests"
    if lower.endswith((".json", ".yaml", ".yml", ".toml")) or lower.endswith((".env.example", ".env.sample")):
        return "config"
    return "source"


def _coverage(review: dict, index: RepositoryIndex, pack: ContextPack) -> dict:
    """What fraction of the diff's own files actually reached the model,
    broken out by why not, so a caller can tell 'nothing relevant here' from
    'this pack has a real blind spot' instead of assuming completeness."""
    changed = [item["path"] for item in review["files"]]
    selected = set(pack.selected_files)
    closure = set(pack.closure_files)
    excluded_reasons = {
        path: reason for path, reason in (index.excluded or {}).items() if path in changed
    }
    not_represented = [
        path for path in changed
        if path not in selected and path not in closure and path not in excluded_reasons
    ]
    by_category: dict[str, dict[str, int]] = {}
    for path in changed:
        category = _evidence_category(path)
        bucket = by_category.setdefault(category, {"total": 0, "selected": 0})
        bucket["total"] += 1
        if path in selected:
            bucket["selected"] += 1
    return {
        "changed_files": len(changed),
        "selected": sorted(selected & set(changed)),
        "closure_only": sorted(closure - selected),
        "excluded_by_policy": excluded_reasons,
        "not_represented": sorted(not_represented),
        "by_category": by_category,
    }


# Categories where, if every one of a diff's changed files in that category
# is newly added (never "modified"), the modified-file priority mechanism
# gives them no help at all -- they'd compete purely on BM25 term-overlap
# against everything else in the diff, including large new source files.
# A migration or CI workflow is inherently review-relevant regardless of
# add/modify status, unlike arbitrary new application code, so these get a
# small guaranteed-but-capped reservation instead (never "source": that
# category is what the existing priority/relevance mechanism already
# handles, and giving it a reservation too would just re-add the risk of
# one category crowding out the others that the cap exists to prevent).
_RESERVABLE_CATEGORIES = {"database", "config", "ci", "tests"}
_CATEGORY_RESERVE_TOTAL_FRACTION = 0.35
# The fair-share recompute below already stops one category from consuming
# the whole reservation when others still need a turn; this is just a
# backstop so a single category (e.g. many small migrations) can't eat
# significantly more than the total reservation on its own.
_CATEGORY_RESERVE_CAP = 1200
_CATEGORY_RESERVE_FLOOR = 150


def _strip_pack_header(text: str) -> str:
    idx = text.find("\n## ")
    return text[idx + 1:] if idx != -1 else text


def build_diff_context(
    root: Path, *, base: str = "HEAD", staged: bool = False,
    max_tokens: int = 6000,
) -> dict:
    review = review_patch(root, base=base, staged=staged)
    parts: list[str] = []
    for item in review["files"]:
        parts.extend([item["path"], *item["symbols"]])
    # Bound the query for large diffs: ranking only needs enough terms to
    # steer relevance, and an unbounded query would blow past max_tokens on
    # its own (see the header-fit fallback in pack.build_context_pack).
    deduped = list(dict.fromkeys(parts))[:60]
    query = "review changed behavior and regressions " + " ".join(deduped)
    changed_paths = {item["path"] for item in review["files"]}
    # Edits to files that already existed carry the regression risk in a diff
    # that mixes a large new addition with a few surgical changes to existing
    # code -- a brand-new file's sheer size/term-overlap can otherwise starve
    # them out of the budget entirely. "not added" is the available signal
    # (git status "A"); a status our own default ("M") or anything else is
    # treated as an edit to something that already existed.
    modified_paths = {
        item["path"] for item in review["files"] if not item["status"].startswith("A")
    }

    underrepresented: dict[str, set[str]] = {}
    for path in changed_paths:
        category = _evidence_category(path)
        if category in _RESERVABLE_CATEGORIES and path not in modified_paths:
            underrepresented.setdefault(category, set()).add(path)

    reserved_texts: list[str] = []
    reserved_selected: list[str] = []
    reserved_symbols: list[str] = []
    reserved_closure: list[str] = []
    claimed_files: set[str] = set()
    reserve_used = 0
    if underrepresented:
        total_cap = int(max_tokens * _CATEGORY_RESERVE_TOTAL_FRACTION)
        # Fair-share what's *left*, recomputed after each category, the same
        # pattern used for priority-file selection in pack.py: a fixed equal
        # split gives a 1-file category (e.g. one new CI workflow) the same
        # budget as a 7-file one (e.g. a batch of migrations), so the small
        # category wastes its share while the large one starves regardless.
        # Processing fewer-file categories first lets them spend only what
        # they need and hand the remainder on, instead of everyone getting
        # an equal slice up front whether they can use it or not.
        ordered = sorted(underrepresented.items(), key=lambda kv: (len(kv[1]), kv[0]))
        categories_left = len(ordered)
        for category, files in ordered:
            fair_share = max((total_cap - reserve_used) // categories_left, _CATEGORY_RESERVE_FLOOR)
            budget = min(fair_share, _CATEGORY_RESERVE_CAP, total_cap - reserve_used)
            categories_left -= 1
            if budget < _CATEGORY_RESERVE_FLOOR:
                continue
            sub_pack = build_context_pack(
                root, f"{category} evidence " + " ".join(sorted(files)),
                max_tokens=budget, changed_boost=True,
                changed_files=files, priority_files=files, restrict_files=files,
            )
            if not sub_pack.selected_files:
                continue
            reserved_texts.append(sub_pack.text)
            reserved_selected.extend(sub_pack.selected_files)
            reserved_symbols.extend(sub_pack.selected_symbols)
            reserved_closure.extend(sub_pack.closure_files)
            claimed_files.update(sub_pack.selected_files)
            reserve_used += sub_pack.estimated_tokens

    remaining_budget = max(max_tokens - reserve_used, _CATEGORY_RESERVE_FLOOR)
    pack = build_context_pack(
        root, query, max_tokens=remaining_budget, changed_boost=True,
        changed_files=changed_paths, priority_files=modified_paths,
        exclude_files=claimed_files or None,
    )

    if reserved_texts:
        combined_text = "\n".join([pack.text.rstrip(), *(_strip_pack_header(t) for t in reserved_texts)]) + "\n"
    else:
        combined_text = pack.text
    combined_tokens = pack.estimated_tokens + reserve_used
    selected_files = [*pack.selected_files, *reserved_selected]
    index = build_index(root)
    combined_pack = ContextPack(
        text=combined_text, estimated_tokens=combined_tokens,
        scanned_files=pack.scanned_files, selected_files=selected_files,
        ranked=pack.ranked, selected_symbols=[*pack.selected_symbols, *reserved_symbols],
        redactions=pack.redactions, closure_files=[*pack.closure_files, *reserved_closure],
    )
    return {
        "review": review,
        "context": combined_pack.text,
        "estimated_tokens": combined_pack.estimated_tokens,
        "selected_files": combined_pack.selected_files,
        "selected_symbols": combined_pack.selected_symbols,
        "closure_files": combined_pack.closure_files,
        "coverage": _coverage(review, index, combined_pack),
    }

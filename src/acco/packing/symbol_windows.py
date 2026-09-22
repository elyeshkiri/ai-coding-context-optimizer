"""Source-window selection and file-section rendering for ranked symbols."""

from __future__ import annotations

from ..lexical import terms
from ..repo_index import RepositoryIndex
from ..security import redact_secrets
from .contracts import RankedFile
from .symbol_scoring import (
    _SymbolScope,
    _apply_parent_credit,
    _build_symbol_scope,
    _contained_children_by_parent,
    _score_symbol,
    _symbol_key,
)

_LARGE_CONTAINER_LINES = 200

def _hit_lines(text: str, query_terms: set[str]) -> list[tuple[int, int]]:
    """Handle hit lines."""
    hits: list[tuple[int, int]] = []
    if not query_terms:
        return hits
    for number, line in enumerate(text.splitlines(), start=1):
        line_terms = set(terms(line))
        overlap = len(query_terms & line_terms)
        if overlap:
            hits.append((number, overlap))
    hits.sort(key=lambda pair: (-pair[1], pair[0]))
    return hits


def _merge_windows(lines: list[int], total: int, radius: int) -> list[tuple[int, int]]:
    """Merge windows."""
    windows = sorted((max(1, n - radius), min(total, n + radius)) for n in lines)
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _merge_ranges(windows: list[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    """Merge ranges."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted((max(1, a), min(total, b)) for a, b in windows):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _source_window(text: str, start: int, end: int) -> str:
    """Handle source window."""
    lines = text.splitlines()
    width = len(str(end))
    body = [f"{n:>{width}}|{lines[n - 1]}" for n in range(start, end + 1)]
    return f"#### lines {start}-{end}\n```\n" + "\n".join(body) + "\n```\n"


def _prioritized_ranges(
    primary: list[tuple[int, int]],
    secondary: list[tuple[int, int]],
    total: int,
) -> list[tuple[int, int]]:
    """Deduplicate source windows without destroying relevance order.

    ``primary`` is already ordered by symbol score. Sorting every window by
    source line lets an earlier-but-weaker definition consume a clipped section
    before a later, higher-scoring symbol. Preserve primary order and append
    lexical navigation windows only when they add source not already covered.
    """
    result: list[tuple[int, int]] = []

    def add(window: tuple[int, int]) -> None:
        start, end = max(1, window[0]), min(total, window[1])
        if start > end:
            return
        for idx, (existing_start, existing_end) in enumerate(result):
            if start <= existing_end + 1 and end >= existing_start - 1:
                result[idx] = (min(start, existing_start), max(end, existing_end))
                return
        result.append((start, end))

    for window in primary:
        add(window)
    for window in secondary:
        add(window)
    return result


def _container_windows(symbol, child) -> list[tuple[int, int]]:
    """Source windows for one selected symbol.

    A container large enough that rendering it in full risks being clipped by
    a tight per-file budget before ever reaching the specific member that
    earned it the boost -- found via a real regression: httpx's ~1400-line
    Client class was truncated well before its credited
    _send_handling_redirects method at line 964, even though the (untruncated)
    window nominally "contained" it. Render a tight window around that member
    instead of the container's full span -- still labeled as the container,
    since that's still why this slot was won, but backed by source that
    actually survives budget fitting regardless of the container's own size.
    Also keep a couple of lines at the container's own declaration so its
    label's line survives too -- omitting it caused a second real regression:
    the container's own label was then stripped as "not visible" by the same
    downstream check this whole fix exists to satisfy.
    """
    return [
        (max(1, symbol.start_line - 1), symbol.start_line + 1),
        (max(1, child.start_line - 1), child.end_line + 1),
    ]


def _render_symbol_windows(
    scope: _SymbolScope, selected: list, best_child_symbol: dict,
    relevant_children_by_parent: dict,
) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Render symbol windows."""
    windows: list[tuple[int, int]] = []
    labels: list[str] = []
    identities: list[str] = []
    for symbol in selected:
        child = best_child_symbol.get(_symbol_key(symbol))
        child_contained = (
            child is not None
            and child.start_line >= symbol.start_line
            and child.end_line <= symbol.end_line
        )
        credit_child_label = child_contained and child not in selected
        is_large = symbol.end_line - symbol.start_line > _LARGE_CONTAINER_LINES
        if child_contained and is_large:
            windows.extend(_container_windows(symbol, child))
        else:
            windows.append((max(1, symbol.start_line - 1), symbol.end_line + 1))
        labels.append(f"{scope.rel}:{symbol.name}@{symbol.start_line}")
        identity_line = symbol.identity_line or symbol.start_line
        identities.append(
            f"{scope.rel}:{symbol.qualified or symbol.name}@{identity_line}"
        )

        # selected_symbols is an evidence ledger, not a strict 1:1 list of
        # rendered windows. When a selected container renders the exact source
        # of multiple relevant members, credit those members too; the downstream
        # visibility filter still drops any label whose declaration line was
        # clipped from the final section. This avoids losing a relevant sibling
        # merely because another member supplied the container's max parent
        # score.
        credited_children = list(
            relevant_children_by_parent.get(_symbol_key(symbol), [])
        )
        if credit_child_label and child not in credited_children:
            credited_children.insert(0, child)
        for credited in credited_children[:3]:
            if credited in selected:
                continue
            labels.append(f"{scope.rel}:{credited.name}@{credited.start_line}")
            credited_identity_line = credited.identity_line or credited.start_line
            identities.append(
                f"{scope.rel}:{credited.qualified or credited.name}"
                f"@{credited_identity_line}"
            )
    return windows, labels, identities


def _symbol_windows(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str],
    target_symbol: str | None, symbol_query_text: str | None = None,
) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Select, score, and render the best symbol windows for one file.

    Pipeline: build the per-file term scope, score every definition, promote
    containers to their best contained member, then render the top two as
    exact source windows with their evidence labels.
    """
    record = index.records.get(item.rel)
    if record is None:
        return [], [], []
    wanted = (target_symbol or "").lower()
    scope = _build_symbol_scope(
        item, record, query_terms, target_symbol, symbol_query_text,
    )

    matches: list[tuple[float, object]] = []
    for symbol in scope.definitions:
        score = _score_symbol(scope, symbol, wanted)
        if score:
            matches.append((score, symbol))

    if not wanted:
        matches, best_child_symbol, containers_by_qualified = _apply_parent_credit(
            scope, matches,
        )
    else:
        best_child_symbol = {}
        containers_by_qualified = {}

    matches.sort(key=lambda pair: (-pair[0], pair[1].start_line, pair[1].name))
    selected = [symbol for _, symbol in matches[:2]]

    relevant_children_by_parent = (
        _contained_children_by_parent(matches, containers_by_qualified)
        if not wanted else {}
    )
    return _render_symbol_windows(
        scope, selected, best_child_symbol, relevant_children_by_parent,
    )


def _file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    index: RepositoryIndex, target_symbol: str | None = None,
    symbol_query_text: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Handle file section."""
    lines = item.text.splitlines()
    symbol_windows, symbol_labels, symbol_identities = _symbol_windows(
        item, index, query_terms, target_symbol, symbol_query_text
    )
    hit_lines = _hit_lines(item.text, query_terms)
    top_numbers = [n for n, _ in hit_lines[:4]]
    lexical = _merge_windows(top_numbers, len(lines), max(0, context_lines))
    semantic = _merge_ranges(item.semantic_ranges, len(lines))
    primary = (
        [*symbol_windows, *semantic]
        if target_symbol
        else [*semantic, *symbol_windows]
    )
    windows = _prioritized_ranges(primary, lexical, len(lines))
    # Exact implementation evidence is the primary payload. Put it before the
    # navigation outline so a tight per-file budget clips optional structure
    # rather than silently dropping the symbol source that caused the file to
    # be selected in the first place.
    pieces = [f"## {item.rel}"]
    if windows:
        pieces.append("### exact source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in windows)
    pieces.extend([
        f"# relevance={item.score:.2f} ({', '.join(item.reasons)})",
        "### outline",
        item.outline.rstrip(),
    ])
    section, redactions = redact_secrets("\n".join(pieces).rstrip() + "\n")
    return section, symbol_labels, symbol_identities, redactions




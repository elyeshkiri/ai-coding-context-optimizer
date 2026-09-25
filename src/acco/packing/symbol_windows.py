"""Source-window selection and file-section rendering for ranked symbols."""

from __future__ import annotations

from ..estimate import estimate_tokens
from ..lexical import terms
from ..repo_index import RepositoryIndex
from ..security import redact_secrets
from .contracts import RankedFile
from .render import _fit_section, _visible_symbol_labels
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


def _append_uncovered(
    windows: list[tuple[int, int]],
    extra: list[tuple[int, int]],
    total: int,
) -> list[tuple[int, int]]:
    """Append only the lines of ``extra`` that no existing window covers.

    Unlike _prioritized_ranges this never widens an earlier window in place:
    merging a low-priority range into a high-priority one moved its source
    ahead of later windows and got those clipped instead.
    """
    covered = [(max(1, start), min(total, end)) for start, end in windows]
    result = list(windows)
    for start, end in extra:
        start, end = max(1, start), min(total, end)
        pieces = [(start, end)]
        for c_start, c_end in covered:
            next_pieces = []
            for p_start, p_end in pieces:
                if p_end < c_start or p_start > c_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if p_start < c_start:
                    next_pieces.append((p_start, c_start - 1))
                if p_end > c_end:
                    next_pieces.append((c_end + 1, p_end))
            pieces = next_pieces
        for piece in pieces:
            if piece[0] <= piece[1]:
                result.append(piece)
                covered.append(piece)
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


_EMPTY_WINDOWS: tuple[list, list, list] = ([], [], [])


def _backfill_candidate(matches: list, selected: list, best_child_symbol: dict):
    """Next distinct definition when a selected slot only repeats rendered source.

    A selected container inherits its best child's score, and its window always
    renders that child. When the child also takes a slot, that slot adds no new
    source. Return the next-best definition not already selected or rendered,
    or None when every selected slot showed something new.
    """
    covered = set()
    for symbol in selected:
        child = best_child_symbol.get(_symbol_key(symbol))
        if (
            child is not None
            and child.start_line >= symbol.start_line
            and child.end_line <= symbol.end_line
        ):
            covered.add(_symbol_key(child))
    if not any(_symbol_key(symbol) in covered for symbol in selected):
        return None
    taken = {_symbol_key(symbol) for symbol in selected} | covered
    for _, symbol in matches:
        if _symbol_key(symbol) not in taken:
            return symbol
    return None


def _symbol_window_plan(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str],
    target_symbol: str | None, symbol_query_text: str | None = None,
) -> tuple[tuple[list, list, list], tuple[list, list, list]]:
    """Primary symbol windows plus an optional lower-priority backfill window.

    Pipeline: build the per-file term scope, score every definition, promote
    containers to their best contained member, then render the top two as
    exact source windows with their evidence labels. When one of those two
    only repeats source its container already renders, the next distinct
    definition is returned separately as a backfill. Callers place it after
    lexical navigation windows so it only ever uses budget nothing else needed.
    """
    record = index.records.get(item.rel)
    if record is None:
        return _EMPTY_WINDOWS, _EMPTY_WINDOWS
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
    primary = _render_symbol_windows(
        scope, selected, best_child_symbol, relevant_children_by_parent,
    )
    backfill_symbol = _backfill_candidate(matches, selected, best_child_symbol)
    if backfill_symbol is None:
        return primary, _EMPTY_WINDOWS
    backfill = _render_symbol_windows(
        scope, [backfill_symbol], best_child_symbol, relevant_children_by_parent,
    )
    return primary, backfill


def _symbol_windows(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str],
    target_symbol: str | None, symbol_query_text: str | None = None,
) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Select, score, and render the best symbol windows for one file."""
    primary, _ = _symbol_window_plan(
        item, index, query_terms, target_symbol, symbol_query_text,
    )
    return primary


def _file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    index: RepositoryIndex, target_symbol: str | None = None,
    symbol_query_text: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Handle file section."""
    lines = item.text.splitlines()
    primary_plan, backfill_plan = _symbol_window_plan(
        item, index, query_terms, target_symbol, symbol_query_text
    )
    symbol_windows, symbol_labels, symbol_identities = primary_plan
    backfill_windows, backfill_labels, backfill_identities = backfill_plan
    hit_lines = _hit_lines(item.text, query_terms)
    top_numbers = [n for n, _ in hit_lines[:4]]
    lexical = _merge_windows(top_numbers, len(lines), max(0, context_lines))
    semantic = _merge_ranges(item.semantic_ranges, len(lines))
    # Embeddings may locate useful implementation ranges, but they are a
    # discovery layer rather than source authority. Parser-backed symbol windows
    # therefore remain first even without an explicit target_symbol; tight
    # per-file budgets clip semantic evidence before exact structural evidence.
    primary = [*symbol_windows, *semantic]
    windows = _prioritized_ranges(primary, lexical, len(lines))
    # Backfill is the lowest-priority evidence in the section, so it is
    # rendered after the outline: section fitting clips from the end, and the
    # outline's numbered lines are themselves visible evidence for credited
    # members. Only source no other window already shows is added.
    backfill = _append_uncovered(windows, backfill_windows, len(lines))[len(windows):]
    symbol_labels = [*symbol_labels, *backfill_labels]
    symbol_identities = [*symbol_identities, *backfill_identities]
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
    if backfill:
        pieces.append("### additional source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in backfill)
    section, redactions = redact_secrets("\n".join(pieces).rstrip() + "\n")
    return section, symbol_labels, symbol_identities, redactions


def _label_line(label: str) -> int | None:
    """Declaration line encoded in a ``path:name@line`` evidence label."""
    try:
        return int(label.rsplit("@", 1)[1])
    except (IndexError, ValueError):
        return None


def _compact_file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    labels: list[str],
) -> str:
    """A section that shows the head of every labeled symbol instead of bodies.

    Used only when the ordinary section must be clipped. Prefix clipping keeps
    whole early windows and drops later declarations entirely, including
    credited members that are only visible through the (often clipped)
    outline. Here each labeled declaration gets a short head window, in label
    order, followed by the usual lexical windows and outline.
    """
    lines = item.text.splitlines()
    radius = max(1, context_lines)
    heads = []
    for label in labels:
        line = _label_line(label)
        if line is not None:
            heads.append((max(1, line - 1), line + radius))
    hit_lines = _hit_lines(item.text, query_terms)
    lexical = _merge_windows(
        [n for n, _ in hit_lines[:4]], len(lines), max(0, context_lines),
    )
    windows = _prioritized_ranges(heads, lexical, len(lines))
    pieces = [f"## {item.rel}"]
    if windows:
        pieces.append("### exact source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in windows)
    pieces.extend([
        f"# relevance={item.score:.2f} ({', '.join(item.reasons)})",
        "### outline",
        item.outline.rstrip(),
    ])
    section, _ = redact_secrets("\n".join(pieces).rstrip() + "\n")
    return section


def _fit_file_section(
    item, q_terms, context_lines, section, section_budget, symbols, identities,
):
    """Fit a section to its budget and return it with its visible evidence.

    When ``section`` had to be clipped, a compact form is tried as well. It is
    used only if it shows every label the clipped section showed plus at least
    one more, in no more tokens. Otherwise the clipped section is kept
    unchanged, so this can add evidence to a file but never remove any.
    """
    fitted = _fit_section(section, section_budget)
    if not fitted:
        return fitted, [], []
    visible = _visible_symbol_labels(fitted, symbols)
    visible_identities = _visible_symbol_labels(fitted, identities)
    if estimate_tokens(section) <= section_budget:
        return fitted, visible, visible_identities
    compact = _fit_section(
        _compact_file_section(item, q_terms, context_lines, symbols),
        section_budget,
    )
    if not compact or estimate_tokens(compact) > estimate_tokens(fitted):
        return fitted, visible, visible_identities
    compact_visible = _visible_symbol_labels(compact, symbols)
    compact_identities = _visible_symbol_labels(compact, identities)
    if (
        set(compact_visible) > set(visible)
        and set(compact_identities) >= set(visible_identities)
    ):
        return compact, compact_visible, compact_identities
    return fitted, visible, visible_identities

"""Budget-allocation policy for final bounded context-pack assembly."""

from __future__ import annotations

_AUTHORITY_SHARE = (3, 5)
_ORDINARY_SHARE = (2, 5)
MIN_COVERAGE_SECTION_TOKENS = 300


def coverage_target(
    *,
    available_tokens: int,
    max_files: int,
    candidate_count: int,
    priority_mode: bool,
) -> int:
    """Return how many leading candidates can receive compact exact evidence."""
    if priority_mode or available_tokens <= 0:
        return 0
    return min(
        max_files,
        candidate_count,
        available_tokens // MIN_COVERAGE_SECTION_TOKENS,
    )


def candidate_section_budget(
    *,
    total_remaining: int,
    candidate_index: int,
    selected_count: int,
    max_files: int,
    candidate_count: int,
    is_priority: bool,
    priority_slots_left: int,
    has_authority: bool,
    coverage_slots: int,
    authoritative_pending: bool,
    authoritative_index: int | None,
    authoritative_reserve: int,
) -> int:
    """Return the current file's budget while reserving later ranked evidence."""
    if total_remaining <= 0:
        return 0

    section_budget = total_remaining
    if is_priority:
        if priority_slots_left > 1:
            section_budget = min(
                section_budget,
                max(total_remaining // priority_slots_left, 200),
            )
    elif (
        selected_count + 1 < max_files
        and candidate_index + 1 < candidate_count
    ):
        share_num, share_den = (
            _AUTHORITY_SHARE if has_authority else _ORDINARY_SHARE
        )
        section_budget = min(
            section_budget,
            max(
                total_remaining * share_num // share_den,
                MIN_COVERAGE_SECTION_TOKENS,
            ),
        )

    reserve = 0
    if coverage_slots and candidate_index < coverage_slots:
        future_slots = max(0, coverage_slots - candidate_index - 1)
        reserve += future_slots * MIN_COVERAGE_SECTION_TOKENS

    if authoritative_pending:
        authority_extra = authoritative_reserve
        if (
            authoritative_index is not None
            and candidate_index < authoritative_index < coverage_slots
        ):
            # Coverage already reserves one compact slot for this provider.
            authority_extra = max(
                0,
                authoritative_reserve - MIN_COVERAGE_SECTION_TOKENS,
            )
        reserve += authority_extra

    if reserve:
        section_budget = min(
            section_budget,
            max(0, total_remaining - reserve),
        )
    return section_budget

"""Budget allocation policy for breadth-preserving context packing."""

from __future__ import annotations

_AUTHORITY_SHARE = (3, 5)
_ORDINARY_SHARE = (2, 5)
_COVERAGE_SLOT_TOKENS = 300
_COVERAGE_RESERVE_SHARE = (3, 5)


def coverage_target(
    usable_tokens: int,
    *,
    max_files: int,
    candidate_count: int,
) -> int:
    """Return how many ranked files should retain a minimum evidence capsule.

    Coverage is bounded by the caller's file limit, available candidates, and
    three fifths of the usable token budget. Very tight budgets still permit
    the normal first candidate instead of forcing an impossible reservation.
    """
    if usable_tokens <= 0 or max_files <= 0 or candidate_count <= 0:
        return 0
    reserve_num, reserve_den = _COVERAGE_RESERVE_SHARE
    reservable = usable_tokens * reserve_num // reserve_den
    by_budget = reservable // _COVERAGE_SLOT_TOKENS
    return min(max_files, candidate_count, max(1, by_budget))


def ranked_candidate_budget(
    remaining: int,
    *,
    selected_count: int,
    coverage_target_count: int,
    has_authority: bool,
) -> int:
    """Return a bounded section budget while preserving ranked-file breadth.

    Until the coverage target is reached, each remaining target slot keeps a
    300-token floor. The current file gets its own floor plus a bounded share
    of surplus: three fifths for structural authority and two fifths otherwise.
    After coverage is satisfied, the historical remaining-budget share applies.
    """
    share_num, share_den = (
        _AUTHORITY_SHARE if has_authority else _ORDINARY_SHARE
    )
    slots = coverage_target_count - selected_count
    if slots <= 0:
        return min(
            remaining,
            max(
                remaining * share_num // share_den,
                _COVERAGE_SLOT_TOKENS,
            ),
        )
    floor_total = slots * _COVERAGE_SLOT_TOKENS
    if remaining <= floor_total:
        return max(1, remaining // max(1, slots))
    surplus = remaining - floor_total
    return min(
        remaining,
        _COVERAGE_SLOT_TOKENS + surplus * share_num // share_den,
    )

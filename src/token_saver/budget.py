"""Adaptive retrieval planning for bounded context packs.

The planner preserves the established 6k behavior while scaling the amount of
retrieval work to the context budget. It only changes retrieval breadth; the
hard final token cap remains enforced by the packer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RetrievalPlan:
    """Represent retrieval plan state and behavior."""
    seed_limit: int
    graph_hops: int
    closure_items: int
    context_lines: int

    def to_dict(self) -> dict[str, int]:
        """Return a dictionary representation."""
        return asdict(self)


def plan_retrieval(
    *,
    max_tokens: int,
    query_terms: int,
    changed_count: int,
    graph_hops: int,
    closure_items: int,
    context_lines: int,
) -> RetrievalPlan:
    """Choose retrieval breadth from the available context budget.

    User-supplied graph depth is never increased. The conventional default
    closure size of 20 is allowed to grow for roomy contexts; custom closure
    limits remain hard upper bounds.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    focused = query_terms >= 3
    if max_tokens <= 2_000:
        seed_limit = 3 if focused else 4
        effective_hops = min(graph_hops, 1)
        effective_closure = min(closure_items, 8)
        effective_context = min(context_lines, 4)
    elif max_tokens <= 7_000:
        # Keep the v1.1 operating point unchanged around its documented 6k
        # benchmark, avoiding quality drift just for the sake of adaptivity.
        seed_limit = 6
        effective_hops = graph_hops
        effective_closure = closure_items
        effective_context = context_lines
    else:
        seed_limit = 8 if focused else 10
        effective_hops = graph_hops
        effective_closure = 30 if closure_items == 20 else closure_items
        effective_context = max(context_lines, 8) if context_lines == 6 else context_lines

    # Large diffs need enough seeds to represent multiple independent edits,
    # but cap breadth so retrieval does not degenerate into a repository dump.
    if changed_count:
        seed_limit = max(seed_limit, min(12, changed_count))

    return RetrievalPlan(
        seed_limit=max(1, seed_limit),
        graph_hops=max(0, effective_hops),
        closure_items=max(0, effective_closure),
        context_lines=max(0, effective_context),
    )

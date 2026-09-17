"""Confidence-aware retrieval budgeting.

The planner is deterministic and deliberately small: it expands farther only
when the ranking is ambiguous and scales dependency closure with the available
context budget. Explicit CLI values still win over automatic choices.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol, Sequence


class _Ranked(Protocol):
    score: float
    term_hits: int
    changed: bool


@dataclass(frozen=True)
class RetrievalPlan:
    seed_count: int
    graph_hops: int
    closure_items: int
    per_file_floor: int
    confidence: float


def _ranking_confidence(ranked: Sequence[_Ranked]) -> float:
    if not ranked:
        return 1.0
    positives = [max(0.0, float(item.score)) for item in ranked[:8] if isfinite(float(item.score))]
    if len(positives) <= 1:
        return 1.0
    top = positives[0]
    second = positives[1]
    if top <= 0:
        return 0.0
    margin = max(0.0, min(1.0, (top - second) / top))
    hit_signal = min(1.0, sum(1 for item in ranked[:4] if item.term_hits or item.changed) / 4.0)
    return max(0.0, min(1.0, margin * 0.65 + hit_signal * 0.35))


def plan_retrieval(
    ranked: Sequence[_Ranked],
    max_tokens: int,
    *,
    graph_hops: int | None = None,
    closure_items: int | None = None,
) -> RetrievalPlan:
    """Choose graph breadth/depth and a fair per-file minimum.

    Low-confidence lexical rankings get more seeds and one extra graph hop;
    high-confidence rankings stay narrow. The hard context cap remains owned by
    the packer, so this planner can never itself exceed the caller's budget.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    confidence = _ranking_confidence(ranked)
    if confidence >= 0.65:
        auto_seeds, auto_hops = 4, 1
    elif confidence >= 0.3:
        auto_seeds, auto_hops = 6, 1
    else:
        auto_seeds, auto_hops = 8, 2
    scaled_closure = max(8, min(48, max_tokens // 220))
    if confidence >= 0.65:
        scaled_closure = min(scaled_closure, 16)
    elif confidence >= 0.3:
        scaled_closure = min(scaled_closure, 28)
    requested_hops = auto_hops if graph_hops is None else graph_hops
    requested_closure = scaled_closure if closure_items is None else closure_items
    if requested_hops < 0 or requested_closure < 0:
        raise ValueError("closure limits must be nonnegative")
    floor = max(140, min(500, max_tokens // max(4, auto_seeds)))
    return RetrievalPlan(auto_seeds, requested_hops, requested_closure, floor, confidence)

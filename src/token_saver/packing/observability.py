"""Structured ranking explanations derived from score traces."""

from __future__ import annotations

import math

from .contracts import RankedFile


def explain_ranked_files(
    query: str,
    ranked: list[RankedFile],
    *,
    max_files: int = 8,
) -> dict:
    """Return stage-by-stage score explanations for the top ranked files."""
    if max_files <= 0:
        raise ValueError("max_files must be positive")

    results: list[dict] = []
    for position, item in enumerate(ranked[:max_files], start=1):
        stage_deltas: dict[str, float] = {}
        for event in item.score_trace:
            stage_deltas[event.stage] = (
                stage_deltas.get(event.stage, 0.0) + event.delta
            )
        trace_end = (
            item.score_trace[-1].after if item.score_trace else item.score
        )
        results.append(
            {
                "rank": position,
                "path": item.rel,
                "final_score": item.score,
                "term_hits": item.term_hits,
                "changed": item.changed,
                "reasons": list(item.reasons),
                "stage_deltas": stage_deltas,
                "trace": [event.to_dict() for event in item.score_trace],
                "trace_complete": math.isclose(
                    trace_end,
                    item.score,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ),
            }
        )
    return {
        "query": query,
        "candidate_count": len(ranked),
        "returned": len(results),
        "results": results,
    }

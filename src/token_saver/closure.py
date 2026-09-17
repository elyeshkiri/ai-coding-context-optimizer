"""Bounded dependency closure for evidence-complete context packs."""

from __future__ import annotations

from dataclasses import dataclass

from .repo_index import RepositoryIndex


@dataclass(frozen=True)
class ClosureItem:
    path: str
    distance: int
    reason: str
    source: str
    confidence: float


EDGE_CONFIDENCE = {
    "semantic-call": 0.99,
    "semantic-ref": 0.0,
    "reexport": 0.93,
    "imports": 0.95,
    "imported-by": 0.9,
    "calls": 0.85,
    "calls-symbol": 0.9,
}


def dependency_closure(
    index: RepositoryIndex,
    seeds: list[str],
    *,
    max_hops: int = 2,
    max_items: int = 20,
    min_confidence: float = 0.5,
) -> list[ClosureItem]:
    """Expand relationships breadth-first with confidence decay and hard limits.

    ``semantic-ref`` is intentionally non-transitive: it is evidence that a
    source mentions an exact imported symbol, not proof that the target file
    belongs in every dependency closure. Query-aware ranking may still consume
    that evidence directly without perturbing unrelated packs.
    """
    if max_hops < 0 or max_items < 0:
        raise ValueError("closure limits must be nonnegative")
    visited = set(seeds)
    frontier = list(dict.fromkeys(seed for seed in seeds if seed in index.records))
    out: list[ClosureItem] = []
    for distance in range(1, max_hops + 1):
        candidates: list[ClosureItem] = []
        for source in frontier:
            for path, edge in index.neighbors(source):
                if path in visited:
                    continue
                confidence = EDGE_CONFIDENCE.get(edge, 0.6) * (0.75 ** (distance - 1))
                if confidence >= min_confidence:
                    candidates.append(ClosureItem(path, distance, edge, source, confidence))
        candidates.sort(key=lambda item: (-item.confidence, item.path, item.source))
        next_frontier = []
        for item in candidates:
            if item.path in visited:
                continue
            visited.add(item.path)
            out.append(item)
            next_frontier.append(item.path)
            if len(out) >= max_items:
                return out
        frontier = next_frontier
        if not frontier:
            break
    return out

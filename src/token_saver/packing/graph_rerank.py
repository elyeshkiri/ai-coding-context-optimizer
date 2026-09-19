"""Graph and optional semantic reranking stages for ranked repository files."""

from __future__ import annotations

from ..closure import authoritative_providers, dependency_closure
from .contracts import RankedFile
from .file_scoring import _FileRankingScope

def _credit_closure(item: RankedFile, related) -> None:
    """Handle credit closure."""
    item.score += 2.5 * related.confidence
    item.reasons.append(f"graph:{related.reason}@{related.distance}")
    item.reasons.append(
        f"closure:{related.source}@{related.distance}:{related.confidence:.2f}"
    )


def _apply_graph_boosts(
    scope: _FileRankingScope, ranked: list[RankedFile],
    priority_files: set[str] | None, seed_limit: int,
    graph_hops: int, closure_max_items: int,
) -> None:
    """Boost files reachable from the top seeds, then authoritative providers."""
    by_rel = {item.rel: item for item in ranked}
    seed_pool = [item.rel for item in ranked if item.term_hits or item.changed]
    if priority_files:
        seed_pool.sort(key=lambda rel: rel not in priority_files)
    seeds = seed_pool[:seed_limit]
    for related in dependency_closure(
        scope.index, seeds, max_hops=graph_hops, max_items=closure_max_items,
    ):
        item = by_rel.get(related.path)
        if item is None:
            continue
        _credit_closure(item, related)

    # dependency_closure above is seeded from only the top seed_limit files
    # (deliberately small/cost-bounded, since most of its edge kinds are
    # transitive and can fan out). A source ranked just below that cutoff --
    # e.g. behind several near-duplicate files that outscore it on raw term
    # overlap alone -- would otherwise never get a chance to surface an exact
    # value it imports. Run the cheap, non-transitive semantic-ref lookup over
    # every relevant candidate instead of just the seed set.
    for related in authoritative_providers(scope.index, seed_pool):
        item = by_rel.get(related.path)
        if item is None or any(
            reason.startswith("graph:") for reason in item.reasons
        ):
            continue
        _credit_closure(item, related)


def _apply_embedding_rerank(
    scope: _FileRankingScope, ranked: list[RankedFile],
) -> None:
    """Optional local-only semantic rerank on top of deterministic ranking."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "embedding reranking requires: pip install 'token-saver[embeddings]'"
        ) from exc
    try:
        model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
    except OSError as exc:
        raise RuntimeError(
            "local embedding model all-MiniLM-L6-v2 is not downloaded"
        ) from exc
    descriptions = [
        f"{item.rel} {' '.join(scope.index.records[item.rel].symbols)} {item.outline}"
        for item in ranked
    ]
    vectors = model.encode([scope.query] + descriptions, normalize_embeddings=True)
    query_vector = vectors[0]
    for item, vector in zip(ranked, vectors[1:]):
        semantic = float(query_vector @ vector)
        item.score += max(0.0, semantic) * 3.0
        item.reasons.append(f"embedding:{semantic:.2f}")



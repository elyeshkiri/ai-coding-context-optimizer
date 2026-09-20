"""Graph and optional semantic reranking stages for ranked repository files."""

from __future__ import annotations

from ..closure import authoritative_providers, dependency_closure
from ..repo_index import RepositoryIndex
from ..semantic_retrieval import SemanticVectorIndex
from .contracts import RankedFile
from .file_scoring import _FileRankingScope
from .ranking_stages import RankingStageContext


class GraphClosureStage:
    """Apply dependency-closure and authoritative-provider score evidence."""

    name = "graph-closure"
    order = 100

    def enabled(self, context: RankingStageContext) -> bool:
        """Run graph evidence for every ranking request, matching legacy behavior."""
        del context
        return True

    def apply(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Apply graph evidence using the request's bounded closure options."""
        options = context.options
        priority_files = (
            set(options.priority_files) if options.priority_files is not None else None
        )
        _apply_graph_boosts_index(
            context.index,
            ranked,
            priority_files,
            options.seed_limit,
            options.graph_hops,
            options.closure_max_items,
        )


class EmbeddingRerankStage:
    """Apply optional local embedding similarity after graph score evidence."""

    name = "embeddings"
    order = 200

    def enabled(self, context: RankingStageContext) -> bool:
        """Run only when embedding reranking was explicitly requested."""
        return context.options.embeddings

    def apply(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Apply the existing local-only embedding reranker."""
        _apply_embedding_rerank_index(context.index, context.query, ranked)


def _credit_closure(item: RankedFile, related) -> None:
    """Credit one closure relationship to a ranked file."""
    item.score += 2.5 * related.confidence
    item.reasons.append(f"graph:{related.reason}@{related.distance}")
    item.reasons.append(
        f"closure:{related.source}@{related.distance}:{related.confidence:.2f}"
    )


def _apply_graph_boosts_index(
    index: RepositoryIndex,
    ranked: list[RankedFile],
    priority_files: set[str] | None,
    seed_limit: int,
    graph_hops: int,
    closure_max_items: int,
) -> None:
    """Boost files reachable from top seeds, then authoritative providers."""
    by_rel = {item.rel: item for item in ranked}
    seed_pool = [item.rel for item in ranked if item.term_hits or item.changed]
    if priority_files:
        seed_pool.sort(key=lambda rel: rel not in priority_files)
    seeds = seed_pool[:seed_limit]
    for related in dependency_closure(
        index,
        seeds,
        max_hops=graph_hops,
        max_items=closure_max_items,
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
    for related in authoritative_providers(index, seed_pool):
        item = by_rel.get(related.path)
        if item is None or any(
            reason.startswith("graph:") for reason in item.reasons
        ):
            continue
        _credit_closure(item, related)


def _apply_graph_boosts(
    scope: _FileRankingScope,
    ranked: list[RankedFile],
    priority_files: set[str] | None,
    seed_limit: int,
    graph_hops: int,
    closure_max_items: int,
) -> None:
    """Preserve the historical scope-based graph helper."""
    _apply_graph_boosts_index(
        scope.index,
        ranked,
        priority_files,
        seed_limit,
        graph_hops,
        closure_max_items,
    )


def _apply_embedding_rerank_index(
    index: RepositoryIndex,
    query: str,
    ranked: list[RankedFile],
) -> None:
    """Fuse chunk-level semantic retrieval with the existing lexical ordering.

    Semantic retrieval is discovery/ranking evidence only. It stores vectors and
    exact source coordinates; final context still comes from the packer's live
    repository reads. RRF-style rank evidence is intentionally bounded so an
    exact structural symbol match remains stronger than fuzzy semantic affinity.
    """
    if not query.strip() or not ranked:
        return
    semantic = SemanticVectorIndex(index.root, index)
    hits = semantic.query(query, top_k=max(40, min(160, len(ranked) * 3)))
    best_by_file = {}
    for hit in hits:
        current = best_by_file.get(hit.path)
        if current is None or (hit.rank, -hit.score) < (current.rank, -current.score):
            best_by_file[hit.path] = hit

    fusion_k = 60.0
    fusion_weight = 240.0
    similarity_weight = 4.0
    lexical_rank = {item.rel: rank for rank, item in enumerate(ranked, start=1)}
    for item in ranked:
        hit = best_by_file.get(item.rel)
        if hit is None:
            continue
        lexical_component = 1.0 / (fusion_k + lexical_rank[item.rel])
        semantic_component = 1.0 / (fusion_k + hit.rank)
        fused = lexical_component + semantic_component
        boost = fusion_weight * fused + similarity_weight * max(0.0, hit.score)
        item.score += boost
        item.reasons.append(hit.evidence())
        item.reasons.append(
            f"hybrid-rrf:{lexical_rank[item.rel]}:{hit.rank}:{boost:.3f}"
        )


def _apply_embedding_rerank(
    scope: _FileRankingScope,
    ranked: list[RankedFile],
) -> None:
    """Preserve the historical scope-based embedding helper."""
    _apply_embedding_rerank_index(scope.index, scope.query, ranked)

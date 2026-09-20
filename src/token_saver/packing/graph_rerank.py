"""Graph and optional semantic reranking stages for ranked repository files."""

from __future__ import annotations

from ..closure import authoritative_providers, dependency_closure
from ..repo_index import RepositoryIndex
from ..semantic_retrieval import SemanticVectorIndex
from .contracts import RankedFile, RankingScoreEvent
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


def _semantic_overlap_ratio(
    left: tuple[int, int],
    right: tuple[int, int],
) -> float:
    """Return overlap relative to the smaller exact-source range."""
    left_start, left_end = left
    right_start, right_end = right
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start) + 1)
    if overlap <= 0:
        return 0.0
    smaller = max(
        1,
        min(left_end - left_start + 1, right_end - right_start + 1),
    )
    return overlap / smaller


def _distinct_semantic_hits(hits, *, max_hits: int = 3):
    """Keep strongest non-redundant semantic evidence per file."""
    selected = []
    for hit in hits:
        current_range = (hit.start_line, hit.end_line)
        if any(
            _semantic_overlap_ratio(
                current_range,
                (existing.start_line, existing.end_line),
            ) >= 0.70
            for existing in selected
        ):
            continue
        selected.append(hit)
        if len(selected) >= max_hits:
            break
    return selected


def _semantic_file_score(hits) -> float:
    """Aggregate multiple independent chunk hits with diminishing returns."""
    if not hits:
        return 0.0
    weights = (1.0, 0.35, 0.15)
    return sum(
        weight * max(0.0, hit.score)
        for weight, hit in zip(weights, hits)
    )


def _apply_semantic_graph_expansion(
    index: RepositoryIndex,
    ranked: list[RankedFile],
    semantic_order: list[str],
) -> None:
    """Credit exact/one-hop providers discovered from semantic witness files."""
    if not semantic_order:
        return
    by_rel = {item.rel: item for item in ranked}
    seeds = semantic_order[:12]

    related = [
        *authoritative_providers(index, seeds),
        *dependency_closure(
            index,
            seeds,
            max_hops=1,
            max_items=24,
            min_confidence=0.8,
        ),
    ]
    strongest = {}
    for item in related:
        current = strongest.get(item.path)
        if current is None or item.confidence > current.confidence:
            strongest[item.path] = item

    for rel, relation in strongest.items():
        item = by_rel.get(rel)
        if item is None:
            continue
        # Keep graph carry-over smaller than direct semantic evidence. Exact
        # semantic-ref/call edges still get enough credit to surface a terse
        # provider when a descriptive caller/test became the semantic witness.
        boost = min(10.0, 2.5 * relation.confidence)
        before = item.score
        item.score += boost
        evidence = (
            f"semantic-graph:{relation.reason}:"
            f"{relation.source}@{relation.distance}:{relation.confidence:.2f}"
        )
        item.reasons.append(evidence)
        item.score_trace.append(
            RankingScoreEvent.from_scores(
                "semantic-graph",
                before,
                item.score,
                (evidence,),
            )
        )


def _apply_embedding_rerank_index(
    index: RepositoryIndex,
    query: str,
    ranked: list[RankedFile],
) -> None:
    """Fuse semantic file discovery with deterministic structural ranking.

    Semantic evidence is aggregated at file level from up to three
    non-overlapping chunks. The semantic boost is intentionally independent of
    lexical rank: BM25/structural evidence has already contributed to the base
    score, so counting lexical rank again would weaken semantic rescue exactly
    when the semantic stage is supposed to discover low-overlap candidates.

    Exact structural authority remains much stronger than the bounded semantic
    boost, and final context rendering still reads current repository bytes.
    """
    if not query.strip() or not ranked:
        return

    semantic = SemanticVectorIndex(index.root, index)
    hits = semantic.query(
        query,
        top_k=min(512, max(96, len(ranked) * 6)),
    )

    by_file = {}
    for hit in hits:
        by_file.setdefault(hit.path, []).append(hit)

    evidence_by_file = {}
    for rel, file_hits in by_file.items():
        selected = _distinct_semantic_hits(file_hits, max_hits=3)
        if selected:
            evidence_by_file[rel] = selected

    semantic_order = sorted(
        evidence_by_file,
        key=lambda rel: (
            -_semantic_file_score(evidence_by_file[rel]),
            evidence_by_file[rel][0].rank,
            rel,
        ),
    )
    semantic_rank = {
        rel: rank
        for rank, rel in enumerate(semantic_order, start=1)
    }

    # The maximum semantic contribution stays bounded to a few dozen points:
    # enough to rescue a semantically strong low-lexical file, but far below
    # explicit structural member/container authority (up to hundreds).
    fusion_k = 40.0
    rank_weight = 700.0
    best_similarity_weight = 8.0
    corroboration_weight = 4.0

    for item in ranked:
        selected = evidence_by_file.get(item.rel)
        if not selected:
            continue

        file_rank = semantic_rank[item.rel]
        best = selected[0]
        secondary = selected[1:]
        rank_boost = rank_weight / (fusion_k + file_rank)
        similarity_boost = best_similarity_weight * max(0.0, best.score)
        corroboration_boost = corroboration_weight * sum(
            max(0.0, hit.score)
            for hit in secondary
        )
        boost = rank_boost + similarity_boost + corroboration_boost

        before = item.score
        item.score += boost
        item.semantic_ranges = [
            (hit.start_line, hit.end_line)
            for hit in selected
        ]
        evidence = (
            *(hit.evidence() for hit in selected),
            (
                f"semantic-file-rank:{file_rank}:"
                f"aggregate={_semantic_file_score(selected):.3f}:"
                f"boost={boost:.3f}"
            ),
        )
        item.reasons.extend(evidence)
        item.score_trace.append(
            RankingScoreEvent.from_scores(
                "hybrid-semantic",
                before,
                item.score,
                evidence,
            )
        )

    _apply_semantic_graph_expansion(index, ranked, semantic_order)


def _apply_embedding_rerank(
    scope: _FileRankingScope,
    ranked: list[RankedFile],
) -> None:
    """Preserve the historical scope-based embedding helper."""
    _apply_embedding_rerank_index(scope.index, scope.query, ranked)

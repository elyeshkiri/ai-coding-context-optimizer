"""Graph and optional semantic reranking stages for ranked repository files."""

from __future__ import annotations

from pathlib import Path

from ..closure import authoritative_providers, dependency_closure
from ..lexical import terms
from ..repo_index import RepositoryIndex
from ..retrieval_vnext import hybrid_file_boost
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



_DESCRIPTOR_FILENAMES = frozenset({
    "module-info.java",
    "package-info.java",
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "go.work",
    "pom.xml",
})
_ANALYZER_ROLE_TERMS = frozenset({
    "analyzer", "analysis", "diagnostic", "lint", "linter", "checker", "inspection",
})
_ANALYZER_QUERY_TERMS = frozenset({
    "analyzer", "analysis", "diagnostic", "lint", "linter", "checker",
    "warning", "warn", "rule", "reported", "report",
})
_MODULE_QUERY_TERMS = frozenset({
    "module", "java", "named", "instrumentation", "export", "exports",
    "requires", "opens", "readability",
})
_PEER_GENERIC_TERMS = frozenset({
    "base", "default", "helper", "helpers", "index", "internal", "main",
    "src", "test", "tests", "util", "utils",
})


def _query_artifact_roles(query: str) -> set[str]:
    """Infer a small set of structural artifact roles from task wording."""
    query_terms = set(terms(query))
    roles: set[str] = set()
    if "module" in query_terms and len(query_terms & _MODULE_QUERY_TERMS) >= 2:
        roles.add("module-descriptor")
    if query_terms & _ANALYZER_QUERY_TERMS:
        roles.add("analyzer")
    return roles


def _file_artifact_roles(rel: str) -> set[str]:
    """Return structural roles encoded by a repository path or filename."""
    path = Path(rel)
    lowered = rel.casefold()
    path_terms = set(terms(rel))
    roles: set[str] = set()
    if path.name.casefold() in _DESCRIPTOR_FILENAMES:
        roles.add("module-descriptor")
    if (
        path_terms & _ANALYZER_ROLE_TERMS
        or "/analyzers/" in f"/{lowered}/"
        or path.stem.casefold().endswith("analyzer")
    ):
        roles.add("analyzer")
    return roles


def _apply_semantic_artifact_authority(
    index: RepositoryIndex,
    ranked: list[RankedFile],
    query: str,
    semantic_order: list[str],
) -> None:
    """Bridge semantic intent to structurally authoritative artifact roles."""
    if not semantic_order:
        return
    query_roles = _query_artifact_roles(query)
    if not query_roles:
        return
    query_terms = set(terms(query))
    for item in ranked:
        matched_roles = query_roles & _file_artifact_roles(item.rel)
        if not matched_roles:
            continue
        record = index.records.get(item.rel)
        document_terms = set((record.term_counts or {}).keys()) if record else set()
        overlap = len(query_terms & document_terms)
        if overlap < 2:
            continue
        boost = min(42.0, 24.0 + 3.0 * overlap)
        before = item.score
        item.score += boost
        evidence = (
            "semantic-artifact-authority:"
            + ",".join(sorted(matched_roles))
            + f":overlap={overlap}:boost={boost:.1f}"
        )
        item.reasons.append(evidence)
        item.score_trace.append(
            RankingScoreEvent.from_scores(
                "semantic-artifact-authority",
                before,
                item.score,
                (evidence,),
            )
        )


def _peer_term_key(term: str) -> str:
    """Normalize one filename-family term without broad query rewriting."""
    value = term.casefold()
    if value.endswith("ing") and len(value) > 6:
        value = value[:-3]
    if value.endswith("e") and len(value) > 4:
        value = value[:-1]
    return value


def _peer_name_terms(rel: str) -> set[str]:
    """Return bounded implementation-family terms from one filename stem."""
    values = {_peer_term_key(value) for value in terms(Path(rel).stem)}
    generic = {_peer_term_key(value) for value in _PEER_GENERIC_TERMS}
    return {value for value in values - generic if len(value) >= 3}


def _apply_semantic_peer_expansion(
    ranked: list[RankedFile],
    query: str,
    semantic_order: list[str],
) -> None:
    """Promote implementation-family peers of strong semantic witness files."""
    if not semantic_order:
        return
    query_terms = {_peer_term_key(value) for value in terms(query)}
    seed_terms = [
        (rel, _peer_name_terms(rel))
        for rel in semantic_order[:12]
    ]
    seed_terms = [(rel, values) for rel, values in seed_terms if values]
    if not seed_terms:
        return

    for item in ranked:
        candidate_terms = _peer_name_terms(item.rel)
        if not candidate_terms:
            continue
        best: tuple[int, int, str, set[str]] | None = None
        for seed, terms_for_seed in seed_terms:
            if seed == item.rel:
                continue
            shared = candidate_terms & terms_for_seed
            if len(shared) < 2:
                continue
            query_shared = shared & query_terms
            if not query_shared and len(shared) < 3:
                continue
            score = (len(shared), len(query_shared), seed, shared)
            if best is None or score[:2] > best[:2]:
                best = score
        if best is None:
            continue
        shared_count, query_shared_count, seed, shared = best
        boost = min(
            20.0,
            6.0 + 3.0 * shared_count + 2.0 * query_shared_count,
        )
        before = item.score
        item.score += boost
        evidence = (
            f"semantic-peer:{seed}:"
            f"shared={','.join(sorted(shared))}:boost={boost:.1f}"
        )
        item.reasons.append(evidence)
        item.score_trace.append(
            RankingScoreEvent.from_scores(
                "semantic-peer",
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

    # Retrieval vNext keeps semantic rescue independent of lexical ordering.
    # Existing lexical/structural scores already live on each RankedFile; the
    # semantic stage therefore uses semantic rank as its primary signal and only
    # small rank-independent corroboration from exact query/path/term evidence.
    lexical_order = {
        item.rel: rank
        for rank, item in enumerate(ranked, start=1)
    }

    for item in ranked:
        selected = evidence_by_file.get(item.rel)
        if not selected:
            continue

        file_rank = semantic_rank[item.rel]
        aggregate = _semantic_file_score(selected)
        hybrid = hybrid_file_boost(
            query=query,
            rel=item.rel,
            semantic_rank=file_rank,
            lexical_rank=lexical_order.get(item.rel, len(ranked) + 1),
            semantic_score=aggregate,
            term_hits=item.term_hits,
            query_views=max((hit.query_views for hit in selected), default=1),
        )
        boost = hybrid.boost

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
                f"aggregate={aggregate:.3f}:"
                f"boost={boost:.3f}"
            ),
            hybrid.reason(),
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
    _apply_semantic_artifact_authority(index, ranked, query, semantic_order)
    _apply_semantic_peer_expansion(ranked, query, semantic_order)


def _apply_embedding_rerank(
    scope: _FileRankingScope,
    ranked: list[RankedFile],
) -> None:
    """Preserve the historical scope-based embedding helper."""
    _apply_embedding_rerank_index(scope.index, scope.query, ranked)

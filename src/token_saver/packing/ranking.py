"""Compatibility facade and orchestrator for file-ranking pipeline stages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..feedback import load_feedback
from ..lexical import symbol_terms
from ..repo_index import RepositoryIndex, build_index
from ..working_set import load_working_set
from .contracts import RankedFile
from .file_scoring import (
    _AUTHORITY_CALLABLE_KINDS as _AUTHORITY_CALLABLE_KINDS,
    _FileRankingScope as _FileRankingScope,
    _GENERIC_CALLABLE_MAX_FILES as _GENERIC_CALLABLE_MAX_FILES,
    _MAX_FILE_BYTES as _MAX_FILE_BYTES,
    _apply_file_boosts as _apply_file_boosts,
    _authority_leaf_terms as _authority_leaf_terms,
    _bm25_score as _bm25_score,
    _callable_file_counts as _callable_file_counts,
    _candidate_documents as _candidate_documents,
    _changed_files as _changed_files,
    _document_terms as _document_terms,
    _leaf_identifier_terms as _leaf_identifier_terms,
    _rank_sort_key as _rank_sort_key,
    _read_source as _read_source,
    _resolve_changed_files as _resolve_changed_files,
    _score_documents as _score_documents,
    _structural_file_authority as _structural_file_authority,
    _terms as _terms,
)
from .graph_rerank import (
    _apply_embedding_rerank as _apply_embedding_rerank,
    _apply_graph_boosts as _apply_graph_boosts,
    _credit_closure as _credit_closure,
)
from .ranking_defaults import DEFAULT_RANKING_STAGE_REGISTRY
from .ranking_stages import (
    RankingStageContext,
    RankingStageOptions,
    RankingStageRegistry,
)
from .query_analysis import (
    _NUMBER_WORDS as _NUMBER_WORDS,
    _callable_signature_terms as _callable_signature_terms,
    _expand_query_terms as _expand_query_terms,
    _generic_arity as _generic_arity,
    _generic_parameter_names as _generic_parameter_names,
    _query_array_preference as _query_array_preference,
    _query_declaration_preference as _query_declaration_preference,
    _query_generic_arity as _query_generic_arity,
    _query_member_hints as _query_member_hints,
    _query_negative_terms as _query_negative_terms,
    _query_parameter_count as _query_parameter_count,
    _query_wants_top_level as _query_wants_top_level,
    _signature_has_implementation as _signature_has_implementation,
    _signature_parameter_count as _signature_parameter_count,
)


def rank_files(
    root: Path,
    query: str,
    *,
    use_gitignore: bool = True,
    changed_boost: bool = True,
    index: RepositoryIndex | None = None,
    graph_hops: int = 1,
    session: str | None = None,
    embeddings: bool = False,
    feedback_boost: bool = True,
    closure_max_items: int = 20,
    changed_files: set[str] | None = None,
    priority_files: set[str] | None = None,
    exclude_files: set[str] | None = None,
    restrict_files: set[str] | None = None,
    seed_limit: int = 6,
    stage_registry: RankingStageRegistry | None = None,
    _symbol_terms_fn: Callable[[str], list[str]] = symbol_terms,
    _load_feedback_fn: Callable[[Path], dict] = load_feedback,
    _structural_authority_fn: Callable = _structural_file_authority,
) -> list[RankedFile]:
    """Rank indexed files for ``query`` using BM25 + code-aware boosts.

    The expensive parse/skeleton/token-frequency work is performed when a file
    enters or changes in the index. Query-time ranking touches only cached
    records; exact source is read later for final context candidates.

    Pipeline: expand the query, collect candidate documents, score each with
    BM25 plus code-aware boosts, then layer graph-closure and optional
    embedding evidence before the final ordering.
    """
    root = root.resolve()
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    if seed_limit <= 0:
        raise ValueError("seed_limit must be positive")
    index = index or build_index(root, use_gitignore=use_gitignore)

    q_terms = _expand_query_terms(index, query)
    changed = _resolve_changed_files(root, changed_boost, changed_files)
    remembered_files, remembered_terms = (
        load_working_set(root, session) if session else (set(), set())
    )
    feedback = _load_feedback_fn(root) if feedback_boost else {}
    query_continues = bool(set(q_terms) & remembered_terms)

    docs = _candidate_documents(root, index, exclude_files, restrict_files)
    if not docs:
        return []

    # Built only once a candidate set exists: _callable_file_counts walks the
    # whole index and is not memoized, so an empty result must not pay for it.
    scope = _FileRankingScope(
        index=index,
        q_terms=q_terms,
        changed=changed,
        feedback=feedback,
        remembered_files=remembered_files,
        query_continues=query_continues,
        authority_terms=set(_symbol_terms_fn(query)),
        authority_pairs=_query_member_hints(query),
        callable_file_counts=_callable_file_counts(index),
        query=query,
        structural_authority=_structural_authority_fn,
    )
    ranked = _score_documents(scope, docs)
    ranked.sort(key=_rank_sort_key)
    registry = stage_registry or DEFAULT_RANKING_STAGE_REGISTRY
    registry.run(
        RankingStageContext(
            index=scope.index,
            query=scope.query,
            options=RankingStageOptions(
                priority_files=(
                    frozenset(priority_files) if priority_files is not None else None
                ),
                seed_limit=seed_limit,
                graph_hops=graph_hops,
                closure_max_items=closure_max_items,
                embeddings=embeddings,
            ),
        ),
        ranked,
    )
    ranked.sort(key=_rank_sort_key)
    return ranked




"""Boundary and parity tests for extracted file-ranking pipeline stages."""

from __future__ import annotations

import inspect
import textwrap

from acco.lexical import symbol_terms
from acco.packing import file_scoring, graph_rerank, query_analysis, ranking
from acco.repo_index import build_index


def _repo(tmp_path):
    """Create a small repository with lexical and graph-ranking evidence."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "patterns.ts").write_text(
        "export const slug = /^[a-z0-9-]+$/;\n",
        encoding="utf-8",
    )
    (src / "validator.ts").write_text(
        textwrap.dedent(
            """
            import * as patterns from "./patterns.js";

            export function validateSlug(value: string) {
              return patterns.slug.test(value);
            }
            """
        ),
        encoding="utf-8",
    )
    (src / "docs.ts").write_text(
        "export function describeSlug() { return 'validate slug request'; }\n",
        encoding="utf-8",
    )
    return tmp_path


def test_ranking_module_is_orchestrator_and_compatibility_facade():
    """Historical ranking helpers should point to extracted implementation stages."""
    source = inspect.getsource(ranking)
    assert source.count("\ndef ") == 1
    assert "def rank_files(" in source
    assert ranking._expand_query_terms is query_analysis._expand_query_terms
    assert ranking._bm25_score is file_scoring._bm25_score
    assert ranking._apply_graph_boosts is graph_rerank._apply_graph_boosts
    rank_source = inspect.getsource(ranking.rank_files)
    assert "DEFAULT_RANKING_STAGE_REGISTRY" in rank_source
    assert "registry.run(" in rank_source
    assert "if embeddings" not in rank_source
    assert "_apply_graph_boosts(" not in rank_source
    assert len(source.splitlines()) < 180


def test_query_analysis_is_independent_from_file_and_graph_scoring():
    """Query interpretation should not depend on downstream scoring/reranking."""
    source = inspect.getsource(query_analysis)
    assert "file_scoring" not in source
    assert "graph_rerank" not in source
    assert "dependency_closure" not in source
    assert "RankedFile" not in source


def test_file_scoring_is_deterministic_and_graph_free():
    """Deterministic scoring should not own closure or embedding policy."""
    source = inspect.getsource(file_scoring)
    assert "dependency_closure" not in source
    assert "authoritative_providers" not in source
    assert "sentence_transformers" not in source
    assert "def _bm25_score(" in source
    assert "def _structural_file_authority(" in source


def test_graph_rerank_does_not_redefine_lexical_scoring():
    """Post-score reranking should consume scored files without duplicating BM25."""
    source = inspect.getsource(graph_rerank)
    assert "def _bm25_score(" not in source
    assert "def _apply_file_boosts(" not in source
    assert "dependency_closure" in source
    assert "authoritative_providers" in source


def test_symbol_scoring_uses_query_analysis_directly():
    """Within-file symbol scoring should bypass the ranking compatibility facade."""
    import acco.packing.symbol_scoring as symbol_scoring

    source = inspect.getsource(symbol_scoring)
    assert "from .query_analysis import" in source
    assert "from .ranking import" not in source


def test_manual_stage_composition_matches_rank_files_exactly(tmp_path):
    """Extracted stages should reproduce final ordering, scores, and reasons exactly."""
    root = _repo(tmp_path)
    index = build_index(root, persist=False)
    query = "validate slug request"

    q_terms = query_analysis._expand_query_terms(index, query)
    docs = file_scoring._candidate_documents(root, index, None, None)
    scope = file_scoring._FileRankingScope(
        index=index,
        q_terms=q_terms,
        changed=set(),
        feedback={},
        remembered_files=set(),
        query_continues=False,
        authority_terms=set(symbol_terms(query)),
        authority_pairs=query_analysis._query_member_hints(query),
        callable_file_counts=file_scoring._callable_file_counts(index),
        query=query,
        structural_authority=file_scoring._structural_file_authority,
    )
    manual = file_scoring._score_documents(scope, docs)
    manual.sort(key=file_scoring._rank_sort_key)
    graph_rerank._apply_graph_boosts(
        scope,
        manual,
        priority_files=None,
        seed_limit=6,
        graph_hops=1,
        closure_max_items=20,
    )
    manual.sort(key=file_scoring._rank_sort_key)

    actual = ranking.rank_files(
        root,
        query,
        changed_boost=False,
        feedback_boost=False,
        index=index,
    )

    def evidence(items):
        """Return stable ranking evidence for exact stage comparison."""
        return [
            (item.rel, item.score, item.reasons, item.term_hits, item.changed)
            for item in items
        ]

    assert evidence(actual) == evidence(manual)

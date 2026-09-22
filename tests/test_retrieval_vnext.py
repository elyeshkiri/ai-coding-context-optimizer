"""Unit tests for retrieval vNext hybrid fusion primitives."""

import pytest

from acco.retrieval_vnext import (
    configured_semantic_model,
    hybrid_file_boost,
)


def test_semantic_model_override_is_explicit(monkeypatch):
    """Code-specialized embeddings must be operator-selected, never implicit."""
    monkeypatch.delenv("ACCO_SEMANTIC_MODEL", raising=False)
    assert configured_semantic_model("all-MiniLM-L6-v2") == "all-MiniLM-L6-v2"
    monkeypatch.setenv("ACCO_SEMANTIC_MODEL", "local/code-model")
    assert configured_semantic_model("all-MiniLM-L6-v2") == "local/code-model"


def test_hybrid_boost_does_not_depend_on_lexical_order():
    """Semantic rescue must not disappear merely because lexical order changed."""
    first = hybrid_file_boost(
        query="refresh authentication session",
        rel="src/session/provider.py",
        semantic_rank=1,
        lexical_rank=1,
        semantic_score=0.91,
        term_hits=2,
        query_views=2,
    )
    second = hybrid_file_boost(
        query="refresh authentication session",
        rel="src/session/provider.py",
        semantic_rank=1,
        lexical_rank=99,
        semantic_score=0.91,
        term_hits=2,
        query_views=2,
    )

    assert first.boost == pytest.approx(second.boost)
    assert first.boost > 20.0
    assert first.lexical_rank != second.lexical_rank


def test_hybrid_boost_allows_zero_lexical_overlap_rescue():
    """A strong semantic hit should still receive a useful bounded contribution."""
    result = hybrid_file_boost(
        query="behavior only natural language description",
        rel="src/opaque/zeta.py",
        semantic_rank=1,
        lexical_rank=100,
        semantic_score=0.95,
        term_hits=0,
        query_views=1,
    )

    assert result.boost > 20.0
    assert result.path_overlap == 0
    assert result.boost <= 34.0

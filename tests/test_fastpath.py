"""Parity tests for the optional Rust acceleration boundary."""

from __future__ import annotations

import math

from token_saver import fastpath


def _reference(monkeypatch):
    """Force and collect Python-reference primitive outputs."""
    monkeypatch.setenv("TOKEN_SAVER_RUST_FASTPATH", "0")
    return {
        "tokens": fastpath.estimate_tokens("αβ auth_service() " * 30, 3.3),
        "identifiers": fastpath.identifier_tokens(
            "Foo foo 2wrong $leading _private abc$def caféValue"
        ),
        "jaccard": fastpath.jaccard_similarity(
            ["auth", "token", "session"],
            ["token", "session", "refresh"],
        ),
        "ngrams": fastpath.char_ngrams("token", 3),
        "bm25": fastpath.bm25_score(
            {"auth": 3, "token": 2},
            ["auth", "token", "missing"],
            {"auth": 2, "token": 3, "missing": 0},
            20,
            18.5,
            8,
        ),
    }


def test_fastpath_python_reference_contract(monkeypatch):
    """The fallback should remain deterministic when Rust is disabled."""
    result = _reference(monkeypatch)

    assert result["tokens"] > 0
    assert "2wrong" not in result["identifiers"]
    assert "$leading" not in result["identifiers"]
    assert "abc$def" in result["identifiers"]
    assert result["jaccard"] == 0.5
    assert result["ngrams"] == ["^to", "tok", "oke", "ken", "en$"]
    assert result["bm25"][0] > 0
    assert result["bm25"][1] == 5
    assert fastpath.status()["backend"] == "python"


def test_compiled_fastpath_matches_python_reference_when_available(monkeypatch):
    """Installing the native extension must not change observable primitives."""
    expected = _reference(monkeypatch)
    monkeypatch.delenv("TOKEN_SAVER_RUST_FASTPATH", raising=False)

    actual = {
        "tokens": fastpath.estimate_tokens("αβ auth_service() " * 30, 3.3),
        "identifiers": fastpath.identifier_tokens(
            "Foo foo 2wrong $leading _private abc$def caféValue"
        ),
        "jaccard": fastpath.jaccard_similarity(
            ["auth", "token", "session"],
            ["token", "session", "refresh"],
        ),
        "ngrams": fastpath.char_ngrams("token", 3),
        "bm25": fastpath.bm25_score(
            {"auth": 3, "token": 2},
            ["auth", "token", "missing"],
            {"auth": 2, "token": 3, "missing": 0},
            20,
            18.5,
            8,
        ),
    }

    assert actual["tokens"] == expected["tokens"]
    assert actual["identifiers"] == expected["identifiers"]
    assert math.isclose(actual["jaccard"], expected["jaccard"], rel_tol=1e-12)
    assert actual["ngrams"] == expected["ngrams"]
    assert math.isclose(actual["bm25"][0], expected["bm25"][0], rel_tol=1e-12)
    assert actual["bm25"][1] == expected["bm25"][1]

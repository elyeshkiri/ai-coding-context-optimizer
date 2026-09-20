"""Tests for persistent hybrid semantic retrieval and exact-source safety."""

from __future__ import annotations

import textwrap

from token_saver.pack import build_context_pack, rank_files
from token_saver.repo_index import build_index
from token_saver.semantic_retrieval import SemanticVectorIndex, semantic_status


class FakeEncoder:
    """Deterministic semantic encoder used without optional ML dependencies."""

    def __init__(self):
        """Track every encoder batch for persistence assertions."""
        self.calls: list[list[str]] = []

    def encode(self, sentences, *, normalize_embeddings=True):
        """Map semantically related fixture phrases onto stable vectors."""
        del normalize_embeddings
        values = list(sentences)
        self.calls.append(values)
        vectors = []
        for text in values:
            lowered = text.lower()
            if (
                "stale_session_artifact" in lowered
                or "expired credentials" in lowered
                or "session artifact timeout" in lowered
            ):
                vectors.append([1.0, 0.0, 0.0])
            elif "invoice" in lowered or "billing" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class FailEncoder:
    """Encoder that proves warm persistent queries perform no model work."""

    def encode(self, sentences, *, normalize_embeddings=True):
        """Fail if a supposedly warm semantic lookup calls the model."""
        del sentences, normalize_embeddings
        raise AssertionError("warm semantic lookup unexpectedly loaded encoder")


def _repo(tmp_path):
    """Create a semantic-retrieval fixture with weak lexical overlap."""
    (tmp_path / "session_guard.py").write_text(
        textwrap.dedent(
            """
            def stale_session_artifact(record):
                if record.timeout_elapsed:
                    return False
                return record.rotate_marker()
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "billing.py").write_text(
        textwrap.dedent(
            """
            def build_invoice(account):
                return account.invoice_total
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_semantic_index_persists_vectors_and_query_embeddings(tmp_path, monkeypatch):
    """An unchanged repository/query should reuse disk state without model calls."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)
    first_encoder = FakeEncoder()
    first = SemanticVectorIndex(root, index, encoder=first_encoder)

    hits = first.query("prevent expired credentials from being reused", top_k=5)

    assert hits[0].path == "session_guard.py"
    assert hits[0].score > 0.99
    assert len(first_encoder.calls) == 2
    assert semantic_status(root)["files"] == 2
    assert semantic_status(root)["chunks"] == 2

    warm = SemanticVectorIndex(root, index, encoder=FailEncoder())
    warm_hits = warm.query("prevent expired credentials from being reused", top_k=5)

    assert warm_hits == hits


def test_semantic_index_reembeds_only_changed_repository_evidence(tmp_path, monkeypatch):
    """A changed file digest should invalidate only that file's persistent vectors."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    first_index = build_index(root, persist=False)
    SemanticVectorIndex(root, first_index, encoder=FakeEncoder()).query(
        "prevent expired credentials from being reused"
    )

    (root / "session_guard.py").write_text(
        textwrap.dedent(
            """
            def stale_session_artifact(record):
                # session artifact timeout semantics changed here
                return record.rotate_marker() if not record.timeout_elapsed else False
            """
        ),
        encoding="utf-8",
    )
    changed_index = build_index(root, persist=False)
    encoder = FakeEncoder()
    refreshed = SemanticVectorIndex(root, changed_index, encoder=encoder)

    hits = refreshed.query("prevent expired credentials from being reused")

    assert hits[0].path == "session_guard.py"
    assert len(encoder.calls) == 1
    embedded = encoder.calls[0]
    assert len(embedded) == 1
    assert "session_guard.py" in embedded[0]


def test_hybrid_rerank_adds_chunk_and_rrf_evidence(tmp_path, monkeypatch):
    """Chunk semantics should become bounded ranking evidence, not replacement text."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)

    monkeypatch.setattr(
        "token_saver.semantic_retrieval._load_encoder",
        lambda _model: FakeEncoder(),
    )
    lexical = rank_files(
        root,
        "prevent expired credentials from being reused",
        changed_boost=False,
        index=index,
        embeddings=False,
    )
    hybrid = rank_files(
        root,
        "prevent expired credentials from being reused",
        changed_boost=False,
        index=index,
        embeddings=True,
    )

    before = next(item for item in lexical if item.rel == "session_guard.py")
    after = next(item for item in hybrid if item.rel == "session_guard.py")
    assert after.score > before.score
    assert any(reason.startswith("semantic-chunk:") for reason in after.reasons)
    assert any(reason.startswith("hybrid-rrf:") for reason in after.reasons)


def test_hybrid_context_pack_still_renders_live_exact_source(tmp_path, monkeypatch):
    """Semantic discovery must finish by rendering repository bytes, not summaries."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)
    monkeypatch.setattr(
        "token_saver.semantic_retrieval._load_encoder",
        lambda _model: FakeEncoder(),
    )

    pack = build_context_pack(
        root,
        "prevent expired credentials from being reused",
        max_tokens=900,
        max_files=2,
        changed_boost=False,
        index=index,
        embeddings=True,
    )

    assert "session_guard.py" in pack.selected_files
    assert "def stale_session_artifact(record):" in pack.text
    assert "return record.rotate_marker()" in pack.text
    assert "semantic summary" not in pack.text.lower()

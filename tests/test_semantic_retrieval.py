"""Tests for persistent hybrid semantic retrieval and exact-source safety."""

from __future__ import annotations

import json
import textwrap

import pytest

from acco.command_handlers.context import semantic_index_main, semantic_status_main
from acco.command_registry import DEFAULT_COMMAND_REGISTRY
from acco.pack import build_context_pack, rank_files
from acco.packing.contracts import RankedFile
from acco.closure import ClosureItem
from acco.packing.graph_rerank import (
    _apply_embedding_rerank_index,
    _apply_semantic_artifact_authority,
    _apply_semantic_graph_expansion,
    _apply_semantic_peer_expansion,
)
from acco.repo_index import RepositoryIndex, build_index, record_for_text
from acco.semantic_retrieval import (
    SemanticHit,
    SemanticVectorIndex,
    _chunk_source,
    _fuse_query_view_hits,
    _semantic_query_views,
    semantic_status,
)


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


class EnsembleEncoder:
    """Encoder fixture where full-query dilution differs from clause intent."""

    def __init__(self):
        """Track batches so warm multi-view cache reuse can be asserted."""
        self.calls: list[list[str]] = []

    def encode(self, sentences, *, normalize_embeddings=True):
        """Map two intent clauses to target while the combined prompt maps noise."""
        del normalize_embeddings
        values = list(sentences)
        self.calls.append(values)
        vectors = []
        for text in values:
            lowered = text.lower()
            has_expired = "expired credentials" in lowered
            has_stale = "stale authentication artifacts" in lowered
            if has_expired and has_stale:
                vectors.append([0.0, 1.0, 0.0])
            elif has_expired or has_stale or "target_behavior_marker" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "noise_behavior_marker" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def _repo(tmp_path):
    """Create a semantic-retrieval fixture with weak lexical overlap."""
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
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

    assert [
        (hit.path, hit.start_line, hit.end_line) for hit in warm_hits
    ] == [
        (hit.path, hit.start_line, hit.end_line) for hit in hits
    ]
    assert warm_hits[0].score == pytest.approx(hits[0].score, abs=1e-5)


def test_semantic_index_reembeds_only_changed_repository_evidence(tmp_path, monkeypatch):
    """A changed file digest should invalidate only that file's persistent vectors."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
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
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)

    monkeypatch.setattr(
        "acco.semantic_retrieval._load_encoder",
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
    assert any(reason.startswith("semantic-file-rank:") for reason in after.reasons)
    assert any(event.stage == "hybrid-semantic" for event in after.score_trace)


def test_hybrid_context_pack_still_renders_live_exact_source(tmp_path, monkeypatch):
    """Semantic discovery must finish by rendering repository bytes, not summaries."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)
    monkeypatch.setattr(
        "acco.semantic_retrieval._load_encoder",
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



def test_semantic_sync_refuses_source_index_digest_race(tmp_path, monkeypatch):
    """Vectors must never be persisted under a stale structural-index digest."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)
    (root / "session_guard.py").write_text(
        "def changed_after_index():\n    return True\n",
        encoding="utf-8",
    )

    semantic = SemanticVectorIndex(root, index, encoder=FakeEncoder())

    with pytest.raises(RuntimeError, match="source changed after repository indexing"):
        semantic.sync()



def test_semantic_cli_build_and_status_are_registered(tmp_path, monkeypatch, capsys):
    """Users should be able to prebuild and inspect vectors without hidden APIs."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    monkeypatch.setattr(
        "acco.semantic_retrieval._load_encoder",
        lambda _model: FakeEncoder(),
    )

    assert {"semantic-index", "semantic-status"} <= set(
        DEFAULT_COMMAND_REGISTRY.names()
    )
    assert semantic_index_main([str(root), "--json"]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["files"] == 2
    assert built["chunks"] == 2
    assert built["dimensions"] == 3

    assert semantic_status_main([str(root), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["files"] == built["files"]
    assert status["chunks"] == built["chunks"]
    assert status["path"] == built["path"]



def test_semantic_model_revision_partitions_persistent_state(tmp_path, monkeypatch):
    """Different model weight revisions must never share stored vectors."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    index = build_index(root, persist=False)

    monkeypatch.setenv("ACCO_SEMANTIC_MODEL_REVISION", "revision-a")
    first = SemanticVectorIndex(root, index, encoder=FakeEncoder())
    first.query("prevent expired credentials from being reused")
    first_path = first.path
    assert first.status().model_revision == "revision-a"

    monkeypatch.setenv("ACCO_SEMANTIC_MODEL_REVISION", "revision-b")
    second_encoder = FakeEncoder()
    second = SemanticVectorIndex(root, index, encoder=second_encoder)
    second.query("prevent expired credentials from being reused")

    assert second.path != first_path
    assert second.status().model_revision == "revision-b"
    assert len(second_encoder.calls) == 2



def test_structure_aware_chunks_embed_signature_parent_and_exact_body(tmp_path):
    """Semantic units should keep declaration metadata attached to live source."""
    root = tmp_path / "repo"
    root.mkdir()
    source = textwrap.dedent(
        """
        class SessionManager:
            def rotate_if_stale(self, record):
                if record.timeout_elapsed:
                    return record.rotate_marker()
                return record
        """
    )
    (root / "session.py").write_text(source, encoding="utf-8")
    index = build_index(root, persist=False)
    record = index.records["session.py"]

    chunks = _chunk_source(
        "session.py",
        source,
        record,
        chunk_lines=64,
        overlap=12,
    )

    structural = [
        rendered
        for _start, _end, rendered, symbol in chunks
        if symbol and "rotate_if_stale" in symbol
    ]
    assert structural
    assert any("signature:" in rendered for rendered in structural)
    assert any("parent: SessionManager" in rendered for rendered in structural)
    assert any("return record.rotate_marker()" in rendered for rendered in structural)


def test_semantic_fusion_keeps_multiple_nonredundant_ranges(tmp_path, monkeypatch):
    """Independent semantic chunks in one file should corroborate file evidence."""
    index = RepositoryIndex(root=tmp_path, records={})
    ranked = [
        RankedFile(
            path=tmp_path / "target.py",
            rel="target.py",
            text="",
            outline="",
            score=5.0,
        ),
        RankedFile(
            path=tmp_path / "noise.py",
            rel="noise.py",
            text="",
            outline="",
            score=12.0,
        ),
    ]

    hits = [
        SemanticHit("target.py", 10, 20, 0.91, 1, "first"),
        SemanticHit("target.py", 60, 72, 0.84, 4, "second"),
        SemanticHit("target.py", 12, 19, 0.88, 2, "overlap"),
        SemanticHit("noise.py", 1, 9, 0.72, 3, "noise"),
    ]

    class FakeSemanticIndex:
        """Return fixed semantic discovery evidence."""

        def __init__(self, root, repository_index):
            del root, repository_index

        def query(self, query, *, top_k):
            del query, top_k
            return hits

    monkeypatch.setattr(
        "acco.packing.graph_rerank.SemanticVectorIndex",
        FakeSemanticIndex,
    )

    _apply_embedding_rerank_index(index, "behavior-only query", ranked)

    target = next(item for item in ranked if item.rel == "target.py")
    assert target.semantic_ranges == [(10, 20), (60, 72)]
    assert sum(
        reason.startswith("semantic-chunk:")
        for reason in target.reasons
    ) == 2
    assert target.score > 5.0


def test_semantic_boost_is_independent_of_lexical_rank(tmp_path, monkeypatch):
    """Changing lexical ordering must not change one file's semantic delta."""
    index = RepositoryIndex(root=tmp_path, records={})

    class FakeSemanticIndex:
        """Return one stable top semantic hit."""

        def __init__(self, root, repository_index):
            del root, repository_index

        def query(self, query, *, top_k):
            del query, top_k
            return [SemanticHit("target.py", 3, 8, 0.9, 1, "target")]

    monkeypatch.setattr(
        "acco.packing.graph_rerank.SemanticVectorIndex",
        FakeSemanticIndex,
    )

    first = [
        RankedFile(tmp_path / "target.py", "target.py", "", "", 50.0),
        RankedFile(tmp_path / "other.py", "other.py", "", "", 10.0),
    ]
    second = [
        RankedFile(tmp_path / "other.py", "other.py", "", "", 100.0),
        RankedFile(tmp_path / "target.py", "target.py", "", "", 5.0),
    ]

    before_first = first[0].score
    before_second = second[1].score
    _apply_embedding_rerank_index(index, "behavior-only query", first)
    _apply_embedding_rerank_index(index, "behavior-only query", second)

    delta_first = first[0].score - before_first
    delta_second = second[1].score - before_second
    assert delta_first == pytest.approx(delta_second)
    assert delta_first > 20.0



def test_semantic_witness_can_promote_one_hop_provider(tmp_path, monkeypatch):
    """A semantic caller/test witness should surface its bounded provider."""
    index = RepositoryIndex(root=tmp_path, records={})
    ranked = [
        RankedFile(tmp_path / "witness.py", "witness.py", "", "", 15.0),
        RankedFile(tmp_path / "provider.py", "provider.py", "", "", 1.0),
    ]

    monkeypatch.setattr(
        "acco.packing.graph_rerank.authoritative_providers",
        lambda repository_index, seeds: [
            ClosureItem(
                path="provider.py",
                distance=1,
                reason="semantic-ref",
                source="witness.py",
                confidence=3.5,
            )
        ],
    )
    monkeypatch.setattr(
        "acco.packing.graph_rerank.dependency_closure",
        lambda *args, **kwargs: [],
    )

    _apply_semantic_graph_expansion(index, ranked, ["witness.py"])

    provider = next(item for item in ranked if item.rel == "provider.py")
    assert provider.score == pytest.approx(9.75)
    assert any(
        reason.startswith("semantic-graph:semantic-ref:witness.py")
        for reason in provider.reasons
    )
    assert any(event.stage == "semantic-graph" for event in provider.score_trace)



def test_short_semantic_query_remains_single_view():
    """Ordinary concise prompts should preserve the historical single-vector path."""
    query = "prevent expired credentials from being reused"

    assert _semantic_query_views(query) == [query]


def test_multiclause_semantic_views_use_only_original_query_vocabulary():
    """Subview extraction must not invent identifiers, synonyms, or model prose."""
    query = (
        "Expired credentials should never be reused after their session timeout. "
        "Stale authentication artifacts must be rejected during renewal rather "
        "than accepted by the active session."
    )

    views = _semantic_query_views(query)

    assert len(views) == 3
    assert views[0] == query
    original_words = set(query.lower().replace(".", "").split())
    for view in views[1:]:
        assert set(view.lower().replace(".", "").split()) <= original_words
    assert "session_guard" not in " ".join(views).lower()
    assert "stale_session_artifact" not in " ".join(views).lower()


def test_long_single_clause_gets_exact_front_and_back_query_windows():
    """Long single-sentence prompts should get bounded exact-word fallback views."""
    words = [
        "investigate", "request", "routing", "behavior", "around", "connection",
        "lifecycle", "when", "multiple", "headers", "arrive", "from", "proxies",
        "while", "authentication", "state", "expires", "during", "renewal",
        "without", "reusing", "stale", "credentials", "or", "cached",
        "authorization", "material", "across", "subsequent", "requests",
    ]
    query = " ".join(words)

    views = _semantic_query_views(query)

    assert len(views) == 3
    assert views[0] == query
    for view in views[1:]:
        assert all(word in words for word in view.split())
        assert len(view.split()) < len(words)


def test_query_view_fusion_rewards_corroborated_chunks():
    """Independent clause agreement should outrank a full-query-only distractor."""
    target = SemanticHit("target.py", 10, 20, 0.93, 1, "target")
    noise = SemanticHit("noise.py", 1, 9, 0.99, 1, "noise")

    fused = _fuse_query_view_hits(
        [
            [noise, SemanticHit("target.py", 10, 20, 0.40, 2, "target")],
            [target],
            [SemanticHit("target.py", 10, 20, 0.91, 1, "target")],
        ],
        top_k=2,
    )

    assert fused[0].path == "target.py"
    assert fused[0].query_views == 3
    assert fused[0].score == pytest.approx(0.93)
    assert fused[1].path == "noise.py"


def test_multiview_query_recovers_target_diluted_by_combined_prompt(
    tmp_path,
    monkeypatch,
):
    """Two exact intent clauses should rescue a target missed by the full vector."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a_noise.py").write_text(
        "def noise_behavior_marker():\n    return 'generic account dashboard'\n",
        encoding="utf-8",
    )
    (root / "z_target.py").write_text(
        "def target_behavior_marker(record):\n"
        "    return not record.timeout_elapsed\n",
        encoding="utf-8",
    )
    index = build_index(root, persist=False)
    encoder = EnsembleEncoder()
    semantic = SemanticVectorIndex(root, index, encoder=encoder)
    query = (
        "Expired credentials should never be reused after their session timeout. "
        "Stale authentication artifacts must be rejected during renewal rather "
        "than accepted by the active session."
    )

    hits = semantic.query(query, top_k=2)

    assert hits[0].path == "z_target.py"
    assert hits[0].query_views >= 2
    assert any(hit.path == "a_noise.py" for hit in hits)


def test_multiview_query_vectors_are_persisted_for_warm_model_free_reuse(
    tmp_path,
    monkeypatch,
):
    """Every deterministic query view should reuse the persistent vector cache."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "target.py").write_text(
        "def target_behavior_marker(record):\n"
        "    return not record.timeout_elapsed\n",
        encoding="utf-8",
    )
    (root / "noise.py").write_text(
        "def noise_behavior_marker():\n    return 'dashboard'\n",
        encoding="utf-8",
    )
    index = build_index(root, persist=False)
    query = (
        "Expired credentials should never be reused after their session timeout. "
        "Stale authentication artifacts must be rejected during renewal rather "
        "than accepted by the active session."
    )
    encoder = EnsembleEncoder()

    first = SemanticVectorIndex(root, index, encoder=encoder)
    initial = first.query(query, top_k=4)

    # One chunk-embedding batch plus one query-vector call per deterministic view.
    assert len(encoder.calls) == 1 + len(_semantic_query_views(query))

    warm = SemanticVectorIndex(root, index, encoder=FailEncoder())
    repeated = warm.query(query, top_k=4)

    assert [
        (hit.path, hit.start_line, hit.end_line, hit.rank)
        for hit in repeated
    ] == [
        (hit.path, hit.start_line, hit.end_line, hit.rank)
        for hit in initial
    ]



def test_process_encoder_cache_reuses_same_model_revision(monkeypatch):
    """Repeated semantic index objects should share one immutable model instance."""
    import sys
    from types import ModuleType

    import acco.semantic_retrieval as semantic_module

    calls = []
    fake_module = ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        """Capture model construction without the optional ML dependency."""

        def __init__(self, model, *, revision=None, local_files_only=False):
            calls.append((model, revision, local_files_only))

    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    semantic_module._load_encoder_cached.cache_clear()
    try:
        monkeypatch.setenv("ACCO_SEMANTIC_MODEL_REVISION", "revision-a")
        first = semantic_module._load_encoder("fixture-model")
        second = semantic_module._load_encoder("fixture-model")

        monkeypatch.setenv("ACCO_SEMANTIC_MODEL_REVISION", "revision-b")
        third = semantic_module._load_encoder("fixture-model")

        assert first is second
        assert third is not first
        assert calls == [
            ("fixture-model", "revision-a", True),
            ("fixture-model", "revision-b", True),
        ]
    finally:
        semantic_module._load_encoder_cached.cache_clear()



def test_medium_long_single_clause_gets_exact_front_and_back_query_windows():
    """Medium-long behavioral prompts should avoid full-query semantic dilution."""
    query = (
        "A mock configured to return itself for fluent calls should not return "
        "the mock for a method whose generic return type resolves to an "
        "incompatible terminal type."
    )

    views = _semantic_query_views(query)

    assert len(views) == 3
    assert views[0] == query
    original = query.split()
    for view in views[1:]:
        assert len(view.split()) < len(original)
        assert all(word in original for word in view.split())


def test_semantic_artifact_authority_promotes_java_module_descriptor(tmp_path):
    """Module-oriented intent should surface a matching Java module descriptor."""
    records = {
        "src/main/java/module-info.java": record_for_text(
            "src/main/java/module-info.java",
            "module org.example { requires java.instrument; exports org.example.internal; }",
        ),
        "src/main/java/org/example/InstrumentationAccessor.java": record_for_text(
            "src/main/java/org/example/InstrumentationAccessor.java",
            "class InstrumentationAccessor { void startAgent() {} }",
        ),
    }
    index = RepositoryIndex(root=tmp_path, records=records)
    ranked = [
        RankedFile(
            tmp_path / "src/main/java/org/example/InstrumentationAccessor.java",
            "src/main/java/org/example/InstrumentationAccessor.java",
            "",
            "",
            40.0,
        ),
        RankedFile(
            tmp_path / "src/main/java/module-info.java",
            "src/main/java/module-info.java",
            "",
            "",
            2.0,
        ),
    ]

    _apply_semantic_artifact_authority(
        index,
        ranked,
        (
            "Named Java modules should not fail during agent startup because "
            "internal classes are inaccessible to the instrumentation module."
        ),
        ["src/main/java/org/example/InstrumentationAccessor.java"],
    )

    descriptor = next(item for item in ranked if item.rel.endswith("module-info.java"))
    assert descriptor.score > 20.0
    assert any(
        reason.startswith("semantic-artifact-authority:module-descriptor")
        for reason in descriptor.reasons
    )


def test_semantic_artifact_authority_promotes_diagnostic_analyzer(tmp_path):
    """Warning-oriented intent should promote a lexically relevant analyzer artifact."""
    records = {
        "src/Runtime/AuthorizationMiddleware.cs": record_for_text(
            "src/Runtime/AuthorizationMiddleware.cs",
            "class AuthorizationMiddleware { void Invoke() {} }",
        ),
        "src/Analyzers/UseAuthorizationAnalyzer.cs": record_for_text(
            "src/Analyzers/UseAuthorizationAnalyzer.cs",
            (
                "class UseAuthorizationAnalyzer { "
                "void Analyze() { ReportDiagnosticForAuthorizationMiddlewareRoutingEndpoint(); } }"
            ),
        ),
    }
    index = RepositoryIndex(root=tmp_path, records=records)
    ranked = [
        RankedFile(
            tmp_path / "src/Runtime/AuthorizationMiddleware.cs",
            "src/Runtime/AuthorizationMiddleware.cs",
            "",
            "",
            50.0,
        ),
        RankedFile(
            tmp_path / "src/Analyzers/UseAuthorizationAnalyzer.cs",
            "src/Analyzers/UseAuthorizationAnalyzer.cs",
            "",
            "",
            3.0,
        ),
    ]

    _apply_semantic_artifact_authority(
        index,
        ranked,
        (
            "Authorization middleware inside a routing branch should not trigger "
            "a warning when endpoint ordering is correct."
        ),
        ["src/Runtime/AuthorizationMiddleware.cs"],
    )

    analyzer = next(item for item in ranked if item.rel.endswith("UseAuthorizationAnalyzer.cs"))
    assert analyzer.score > 25.0
    assert any(
        reason.startswith("semantic-artifact-authority:analyzer")
        for reason in analyzer.reasons
    )


def test_semantic_peer_expansion_promotes_parallel_provider_family(tmp_path):
    """A strong semantic provider may surface a parallel implementation peer."""
    ranked = [
        RankedFile(
            tmp_path / "src/OutputCacheKeyProvider.cs",
            "src/OutputCacheKeyProvider.cs",
            "",
            "",
            60.0,
        ),
        RankedFile(
            tmp_path / "src/ResponseCachingKeyProvider.cs",
            "src/ResponseCachingKeyProvider.cs",
            "",
            "",
            4.0,
        ),
        RankedFile(
            tmp_path / "src/UnrelatedHandler.cs",
            "src/UnrelatedHandler.cs",
            "",
            "",
            10.0,
        ),
    ]

    _apply_semantic_peer_expansion(
        ranked,
        (
            "Cache keys must distinguish multiple vary header values so "
            "different requests cannot collide."
        ),
        ["src/OutputCacheKeyProvider.cs"],
    )

    peer = next(item for item in ranked if item.rel.endswith("ResponseCachingKeyProvider.cs"))
    unrelated = next(item for item in ranked if item.rel.endswith("UnrelatedHandler.cs"))
    assert peer.score > 15.0
    assert unrelated.score == 10.0
    assert any(reason.startswith("semantic-peer:") for reason in peer.reasons)


def test_semantic_peer_expansion_rejects_single_generic_name_overlap(tmp_path):
    """One broad filename token is insufficient semantic peer evidence."""
    ranked = [
        RankedFile(tmp_path / "src/CacheProvider.cs", "src/CacheProvider.cs", "", "", 20.0),
        RankedFile(tmp_path / "src/AuthProvider.cs", "src/AuthProvider.cs", "", "", 5.0),
    ]

    _apply_semantic_peer_expansion(
        ranked,
        "cache entries should preserve multiple values",
        ["src/CacheProvider.cs"],
    )

    candidate = next(item for item in ranked if item.rel.endswith("AuthProvider.cs"))
    assert candidate.score == 5.0
    assert not any(reason.startswith("semantic-peer:") for reason in candidate.reasons)

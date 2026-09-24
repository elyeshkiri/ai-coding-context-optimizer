from pathlib import Path
import textwrap

import acco.pack as pack_module
from acco.pack import build_context_pack, rank_files
from acco.repo_index import build_index, similarity


def _repo(root):
    src = root / "src"
    src.mkdir(parents=True)
    (src / "service.py").write_text(textwrap.dedent("""
        from src.repository import load_user

        def refresh_session(user_id):
            return load_user(user_id)
    """))
    (src / "repository.py").write_text(textwrap.dedent("""
        def load_user(user_id):
            return {"id": user_id}
    """))
    (src / "unrelated.py").write_text("def render_invoice():\n    return 'invoice'\n")
    return root


def test_incremental_index_reuses_unchanged_records(tmp_path):
    root = _repo(tmp_path)
    cache = tmp_path / "index.json"
    first = build_index(root, cache_path=cache)
    second = build_index(root, cache_path=cache)
    assert first.reparsed == 3
    assert second.reparsed == 0
    assert second.reused == 3

    (root / "src" / "service.py").write_text("def refresh_session():\n    return None\n")
    third = build_index(root, cache_path=cache)
    assert third.reparsed == 1
    assert third.reused == 2


def test_warm_index_does_not_reopen_unchanged_source(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    cache = tmp_path / "index.json"
    build_index(root, cache_path=cache)
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if path.suffix == ".py":
            raise AssertionError(f"warm index reopened source: {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    warm = build_index(root, cache_path=cache)
    assert warm.reparsed == 0
    assert warm.reused == 3


def test_index_persists_retrieval_payload(tmp_path):
    index = build_index(_repo(tmp_path), persist=False)
    service = index.records["src/service.py"]
    assert service.outline
    assert service.term_counts
    assert service.document_length > 0
    assert service.term_counts.get("refresh", 0) > 0


def test_index_extracts_symbols_imports_calls_and_edges(tmp_path):
    index = build_index(_repo(tmp_path), persist=False)
    service = index.records["src/service.py"]
    assert "refresh_session" in service.symbols
    assert "src.repository" in service.imports
    assert "load_user" in service.calls
    assert ("src/repository.py", "imports") in index.neighbors("src/service.py")


def test_rank_files_uses_index_without_source_hydration(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)

    def forbidden(_path):
        raise AssertionError("rank_files must not hydrate source")

    monkeypatch.setattr(pack_module, "_read_source", forbidden)
    ranked = rank_files(
        root, "refresh session", index=index, graph_hops=1, changed_boost=False
    )
    assert ranked[0].rel == "src/service.py"
    assert all(item.text == "" for item in ranked)


def test_context_pack_hydrates_only_final_candidates(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)
    original = pack_module._read_source
    reads = []

    def counted(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(pack_module, "_read_source", counted)
    pack = build_context_pack(
        root, "refresh session", index=index, max_files=1, max_tokens=800,
        graph_hops=0, changed_boost=False,
    )
    assert pack.selected_files == ["src/service.py"]
    assert reads == [root / "src/service.py"]


def test_graph_expansion_promotes_dependency(tmp_path):
    root = _repo(tmp_path)
    no_graph = rank_files(root, "refresh session", graph_hops=0, changed_boost=False)
    graph = rank_files(root, "refresh session", graph_hops=1, changed_boost=False)
    before = next(item.score for item in no_graph if item.rel == "src/repository.py")
    related = next(item for item in graph if item.rel == "src/repository.py")
    assert related.score > before
    assert any(reason.startswith("graph:imports") for reason in related.reasons)


def test_near_duplicates_are_suppressed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    body = "def refresh_session(token):\n    account = lookup(token)\n    return rotate(account)\n"
    (src / "auth.py").write_text(body)
    (src / "auth_copy.py").write_text(body.replace("refresh_session", "refresh_session_copy"))
    pack = build_context_pack(
        tmp_path, "refresh session token account", max_tokens=1200,
        duplicate_threshold=0.70, changed_boost=False, persist_index=False,
    )
    assert len(pack.selected_files) == 1
    assert any("near-duplicate-skipped" in item.reasons for item in pack.ranked)


def test_similarity_ignores_formatting(tmp_path):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)
    left = index.records["src/service.py"]
    right = type(left)(**{**left.__dict__, "path": "copy.py", "digest": "different"})
    assert similarity(left, right) == 1.0


def test_working_set_boosts_continuation(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    first = build_context_pack(
        root, "refresh session", session="issue-42", max_tokens=800,
        changed_boost=False, persist_index=False,
    )
    assert "src/service.py" in first.selected_files
    ranked = rank_files(
        root, "session followup", session="issue-42", graph_hops=0,
        changed_boost=False,
    )
    service = next(item for item in ranked if item.rel == "src/service.py")
    assert "working-set" in service.reasons


def test_embedding_mode_has_actionable_missing_dependency_error(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    import builtins
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    try:
        rank_files(root, "refresh", embeddings=True, changed_boost=False)
    except RuntimeError as exc:
        assert "acco[embeddings]" in str(exc)
    else:
        raise AssertionError("expected missing optional dependency error")


def test_python_outline_leads_with_module_summary(tmp_path):
    (tmp_path / "tool.py").write_text(
        '"""Paired end-to-end task evaluation.\n\nMore detail.\n"""\n\ndef evaluate():\n    pass\n',
        encoding="utf-8",
    )
    outline = build_index(tmp_path, persist=False).records["tool.py"].outline
    assert outline.splitlines()[0].endswith("# Paired end-to-end task evaluation.")
    assert "More detail" not in outline


def test_argparse_flags_count_for_relevance_but_stay_out_of_outline(tmp_path):
    (tmp_path / "cli.py").write_text(
        "import argparse\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--target-symbol')\n"
        "    parser.add_argument(\"--json\", action='store_true')\n",
        encoding="utf-8",
    )
    from acco.lexical import document_counts

    text = (tmp_path / "cli.py").read_text(encoding="utf-8")
    record = build_index(tmp_path, persist=False).records["cli.py"]
    without_flags = document_counts(text, record.outline, "cli.py")

    assert "--target-symbol" not in record.outline
    for term in ("target", "symbol", "json"):
        assert record.term_counts[term] > without_flags.get(term, 0)

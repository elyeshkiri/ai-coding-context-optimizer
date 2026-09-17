import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from token_saver.adaptive_budget import plan_retrieval
from token_saver.entry import main as entry_main
from token_saver.estimate import Counter
from token_saver.host_validate import _transport_roundtrip
from token_saver.pack import build_context_pack, rank_files
from token_saver.repo_index import build_index
from token_saver.semantic_ts import resolve_typescript_edges
from token_saver.unseen_eval import evaluate_unseen_suite, ground_truth_hash


def _repo(root: Path) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "auth.py").write_text(
        "def refresh_session(token):\n"
        "    account = lookup_account(token)\n"
        "    return rotate_session(account)\n",
        encoding="utf-8",
    )
    (src / "store.py").write_text(
        "def lookup_account(token):\n    return {'token': token}\n",
        encoding="utf-8",
    )
    (src / "billing.py").write_text(
        "def render_invoice(customer):\n    return customer\n",
        encoding="utf-8",
    )
    return root


def test_index_persists_retrieval_metadata(tmp_path):
    root = _repo(tmp_path / "repo")
    cache = tmp_path / "index.json"
    first = build_index(root, cache_path=cache)
    record = first.records["src/auth.py"]
    assert record.outline
    assert record.term_counts
    assert record.term_counts.get("refresh", 0) > 0

    second = build_index(root, cache_path=cache)
    assert second.reparsed == 0
    assert second.reused == 3
    assert second.records["src/auth.py"].term_counts == record.term_counts


def test_rank_files_is_index_only_after_index_build(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)

    def forbidden(_path):
        raise AssertionError("ranking should not open source bodies")

    monkeypatch.setattr("token_saver.indexed_pack_core._read_source", forbidden)
    ranked = rank_files(root, "refresh session", index=index, changed_boost=False)
    assert ranked[0].rel == "src/auth.py"


def test_warm_rank_reuses_index_without_reopening_source(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    # First query intentionally performs the conservative digest-backed build
    # and writes the stat sidecar.
    first = rank_files(root, "refresh session", changed_boost=False)
    assert first[0].rel == "src/auth.py"

    def forbidden(_path):
        raise AssertionError("warm rank reopened unchanged source")

    monkeypatch.setattr("token_saver.fast_index._read_text", forbidden)
    second = rank_files(root, "refresh session", changed_boost=False)
    assert second[0].rel == "src/auth.py"


def test_warm_rank_reopens_only_changed_source(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path / "repo")
    rank_files(root, "refresh session", changed_boost=False)
    auth = root / "src" / "auth.py"
    auth.write_text(auth.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    import token_saver.fast_index as fast_index
    original = fast_index._read_text
    opened = []

    def tracked(path):
        opened.append(path.relative_to(root).as_posix())
        return original(path)

    monkeypatch.setattr(fast_index, "_read_text", tracked)
    rank_files(root, "refresh session", changed_boost=False)
    assert opened == ["src/auth.py"]


def test_context_pack_lazily_hydrates_selected_evidence(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)
    import token_saver.indexed_pack_core as indexed_pack

    original = indexed_pack._read_source
    opened = []

    def tracked(path):
        opened.append(path)
        return original(path)

    monkeypatch.setattr(indexed_pack, "_read_source", tracked)
    pack = build_context_pack(
        root, "refresh session", index=index, changed_boost=False,
        max_files=1, max_tokens=800,
    )
    assert pack.selected_files == ["src/auth.py"]
    assert opened == [root / "src/auth.py"]


def test_semantic_edges_override_name_heuristics(tmp_path):
    root = _repo(tmp_path)
    index = build_index(root, persist=False)
    index.records["src/auth.py"].semantic_refs = ["src/store.py"]
    assert ("src/store.py", "semantic") in index.neighbors("src/auth.py")
    assert ("src/auth.py", "semantic-reverse") in index.neighbors("src/store.py")


def test_typescript_semantic_resolver_falls_back_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr("token_saver.semantic_ts.shutil.which", lambda _name: None)
    assert resolve_typescript_edges(tmp_path) == {}
    with pytest.raises(RuntimeError, match="Node.js"):
        resolve_typescript_edges(tmp_path, strict=True)


def test_adaptive_budget_expands_ambiguous_rankings():
    ambiguous = [
        SimpleNamespace(score=10.0, term_hits=0, changed=False),
        SimpleNamespace(score=9.9, term_hits=0, changed=False),
        SimpleNamespace(score=9.8, term_hits=0, changed=False),
    ]
    confident = [
        SimpleNamespace(score=20.0, term_hits=3, changed=False),
        SimpleNamespace(score=2.0, term_hits=0, changed=False),
    ]
    broad = plan_retrieval(ambiguous, 6000)
    narrow = plan_retrieval(confident, 6000)
    assert broad.graph_hops == 2
    assert broad.seed_count > narrow.seed_count
    assert narrow.graph_hops == 1


def test_unseen_suite_requires_frozen_ground_truth(tmp_path):
    repo = _repo(tmp_path / "external")
    manifest = tmp_path / "suite.json"
    payload = {
        "suite_version": 1,
        "frozen_at": "2026-09-17T12:00:00Z",
        "tasks": [{
            "id": "external-auth",
            "repo": str(repo),
            "query": "refresh session",
            "files": ["src/auth.py"],
            "symbols": ["refresh_session"],
            "max_tokens": 800,
        }],
    }
    payload["ground_truth_sha256"] = ground_truth_hash(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    result = evaluate_unseen_suite(manifest, adaptive_budget=False)
    assert result["frozen"] is True
    assert result["summary"]["mean_file_recall"] == 1.0

    payload["tasks"][0]["query"] = "different task after freeze"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="ground truth"):
        evaluate_unseen_suite(manifest)


def test_provider_counter_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unsupported token provider"):
        Counter(provider="unknown")  # type: ignore[arg-type]


def test_provider_aware_estimate_command_routes_without_network(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("hello provider-aware tokens"))
    assert entry_main(["estimate", "--provider", "openai"]) == 0
    output = capsys.readouterr().out
    assert "provider=openai" in output
    assert "≈est" in output


def test_hook_transport_roundtrip_recovers_omitted_middle(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    result = _transport_roundtrip()
    assert result["ok"] is True
    assert result["recovery_verified"] is True
    assert result["replacement_lines"] < result["original_lines"]


def test_pack_adaptive_mode_is_visible(tmp_path):
    root = _repo(tmp_path)
    pack = build_context_pack(
        root, "refresh session", changed_boost=False,
        adaptive_budget=True, max_tokens=800,
    )
    assert "# mode: indexed, adaptive" in pack.text

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from token_saver.evaluate import evaluate_manifest
from token_saver.feedback import load_feedback, record_feedback
from token_saver.impact import analyze_impact
from token_saver.pack import build_context_pack, rank_files
from token_saver.repo_index import build_index
from token_saver.security import inspect_path, redact_secrets
from token_saver.serve import call_tool, handle_message


def _project(root):
    src = root / "src"
    tests = root / "tests"
    src.mkdir(parents=True)
    tests.mkdir()
    (src / "repository.py").write_text(textwrap.dedent("""
        def load_user(user_id: str) -> dict:
            return {"id": user_id}
    """))
    (src / "service.py").write_text(textwrap.dedent("""
        from src.repository import load_user

        class SessionService:
            def refresh_session(self, user_id: str) -> dict:
                return load_user(user_id)

            def unrelated_method(self) -> str:
                return "unrelated"
    """))
    (tests / "test_service.py").write_text(textwrap.dedent("""
        from src.service import SessionService

        def test_refresh_session():
            assert SessionService().refresh_session("1")
    """))
    return root


def test_index_persists_symbol_ranges_signatures_and_calls(tmp_path):
    index = build_index(_project(tmp_path), persist=False)
    service = index.records["src/service.py"]
    refresh = next(item for item in service.definitions if item.name == "refresh_session")
    assert refresh.start_line < refresh.end_line
    assert "user_id: str" in refresh.signature
    assert refresh.parent == "SessionService"
    assert "load_user" in refresh.calls
    assert index.find_symbols("refresh_session") == [("src/service.py", refresh)]


def test_target_symbol_emits_complete_body_and_metadata(tmp_path):
    root = _project(tmp_path)
    pack = build_context_pack(
        root, "session bug", target_symbol="refresh_session",
        max_tokens=800, changed_boost=False, persist_index=False,
    )
    assert "return load_user(user_id)" in pack.text
    assert any(value.startswith("src/service.py:refresh_session@") for value in pack.selected_symbols)


def test_symbol_is_selected_from_task_terms_in_its_body(tmp_path):
    source = tmp_path / "dispatcher.py"
    source.write_text(textwrap.dedent("""
        def main(argv):
            if argv[0] == "impact":
                return analyze_change_impact(argv[1])
            return build_context(argv)
    """))
    pack = build_context_pack(
        tmp_path, "dispatch impact context command", max_tokens=500,
        changed_boost=False, persist_index=False,
    )
    assert any(":main@" in value for value in pack.selected_symbols)


def test_impact_reports_callers_dependencies_and_tests(tmp_path):
    report = analyze_impact(_project(tmp_path), "load_user")
    reasons = {(item.path, item.reason) for item in report.affected}
    assert ("src/service.py", "calls-symbol") in reasons
    assert any(path == "tests/test_service.py" for path, _ in reasons)


def test_feedback_is_bounded_and_changes_ranking(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _project(tmp_path / "repo")
    for _ in range(20):
        record_feedback(root, "src/repository.py", useful=True)
    assert load_feedback(root)["src/repository.py"] == 10
    ranked = rank_files(root, "user", graph_hops=0, changed_boost=False)
    repository = next(item for item in ranked if item.rel == "src/repository.py")
    assert "feedback:+10" in repository.reasons


def test_evaluator_measures_file_symbol_recall_and_reduction(tmp_path):
    root = _project(tmp_path)
    manifest = tmp_path / "tasks.json"
    manifest.write_text(json.dumps({"tasks": [{
        "id": "session", "query": "refresh session user",
        "files": ["src/service.py"], "symbols": ["refresh_session"],
    }]}))
    result = evaluate_manifest(root, manifest, max_tokens=800)
    assert result["summary"]["task_count"] == 1
    assert result["summary"]["mean_file_recall"] == 1.0
    assert result["summary"]["mean_symbol_recall"] == 1.0
    assert 0.0 <= result["summary"]["mean_token_reduction"] <= 1.0


def test_evaluator_ignores_worktree_and_learned_ranking_state(tmp_path, monkeypatch):
    root = _project(tmp_path / "repo")
    manifest = tmp_path / "tasks.json"
    manifest.write_text(json.dumps({"tasks": [{
        "query": "refresh session", "files": ["src/service.py"],
        "symbols": ["refresh_session"],
    }]}))
    monkeypatch.setattr("token_saver.pack._changed_files", lambda _root: {"src/repository.py"})
    monkeypatch.setattr("token_saver.pack.load_feedback", lambda _root: {"src/repository.py": 10})
    result = evaluate_manifest(root, manifest, max_tokens=500)
    assert result["summary"]["mean_file_recall"] == 1.0


def test_sensitive_paths_and_inline_secrets_are_protected(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("API_KEY=super-secret")
    assert inspect_path(tmp_path, secret).reason == "sensitive-path"
    redacted, labels = redact_secrets('api_key = "super-secret-value"')
    assert "super-secret-value" not in redacted
    assert labels == ["generic-secret"]
    private = "-----BEGIN PRIVATE KEY-----\nsecret-material\n-----END PRIVATE KEY-----"
    redacted, labels = redact_secrets(private)
    assert "secret-material" not in redacted and labels == ["private-key"]


def test_symlinks_are_not_indexed(tmp_path):
    root = _project(tmp_path)
    link = root / "src" / "linked.py"
    try:
        link.symlink_to(root / "src" / "service.py")
    except OSError:
        pytest.skip("symlinks unavailable")
    index = build_index(root, persist=False)
    assert "src/linked.py" not in index.records


def test_mcp_server_lists_tools_and_calls_symbol_lookup(tmp_path):
    root = _project(tmp_path)
    listed = handle_message(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"build_context", "find_symbol", "analyze_change_impact"} <= names
    result = call_tool(root, "find_symbol", {"name": "refresh_session"})
    payload = json.loads(result["content"][0]["text"])
    assert payload[0]["path"] == "src/service.py"


def test_mcp_unknown_tool_is_an_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="unknown tool"):
        call_tool(_project(tmp_path), "missing", {})


def test_corrupt_index_cache_fails_open(tmp_path):
    root = _project(tmp_path / "repo")
    cache = tmp_path / "index.json"
    cache.write_text('{"version":2,"records":{"bad":42}}')
    index = build_index(root, cache_path=cache)
    assert "src/service.py" in index.records
    if os.name != "nt":
        assert cache.stat().st_mode & 0o077 == 0


def test_stdio_mcp_handshake_and_symbol_call(tmp_path):
    root = _project(tmp_path)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "find_symbol", "arguments": {"name": "refresh_session"},
        }},
    ]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "token_saver.entry", "serve", str(root)],
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True, text=True, env=env, timeout=10, check=True,
    )
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert responses[0]["result"]["serverInfo"]["version"] == "1.0.0"
    assert any(tool["name"] == "build_context" for tool in responses[1]["result"]["tools"])
    assert "refresh_session" in responses[2]["result"]["content"][0]["text"]

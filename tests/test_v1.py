import json
import subprocess
import textwrap

import pytest

from token_saver.agent_eval import evaluate_agent_runs
from token_saver.closure import dependency_closure
from token_saver.patch_context import build_diff_context, collect_patch, review_patch
from token_saver.repo_index import build_index
from token_saver.serve import IndexService, call_tool


def _graph_repo(root):
    src = root / "src"
    tests = root / "tests"
    src.mkdir(parents=True)
    tests.mkdir()
    (src / "repository.py").write_text("def load_user(user_id):\n    return {'id': user_id}\n")
    (src / "service.py").write_text(textwrap.dedent("""
        from src.repository import load_user
        def refresh_session(user_id):
            return load_user(user_id)
    """))
    (tests / "test_service.py").write_text(textwrap.dedent("""
        from src.service import refresh_session
        def test_refresh():
            assert refresh_session("1")
    """))
    return root


def _git_repo(root):
    _graph_repo(root)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
    return root


def test_tree_sitter_index_has_exact_typescript_ranges_and_parent(tmp_path):
    source = tmp_path / "service.ts"
    source.write_text(textwrap.dedent("""
        export class SessionService {
          refreshSession(token: string): string {
            return rotateToken(token)
          }
        }
    """))
    index = build_index(tmp_path, persist=False)
    refresh = next(symbol for symbol in index.records["service.ts"].definitions
                   if symbol.name == "refreshSession")
    assert refresh.end_line > refresh.start_line
    assert refresh.parent == "SessionService"
    assert "rotateToken" in refresh.calls


def test_dependency_closure_is_bounded_explained_and_ordered(tmp_path):
    index = build_index(_graph_repo(tmp_path), persist=False)
    closure = dependency_closure(index, ["src/repository.py"], max_hops=2, max_items=2)
    assert closure
    assert len(closure) <= 2
    assert closure[0].reason in {"imported-by", "calls-symbol"}
    assert closure[0].source == "src/repository.py"
    assert 0 < closure[0].confidence <= 1


def test_patch_collection_maps_added_lines_to_changed_symbol(tmp_path):
    root = _git_repo(tmp_path)
    service = root / "src" / "service.py"
    service.write_text(textwrap.dedent("""
        from src.repository import load_user
        def refresh_session(user_id, force=False):
            user = load_user(user_id)
            return {**user, "force": force}
    """))
    changes = collect_patch(root)
    assert [change.path for change in changes] == ["src/service.py"]
    report = review_patch(root)
    item = report["files"][0]
    assert "refresh_session" in item["symbols"]
    assert "refresh_session" in item["signature_changes"]
    assert any(warning["code"] == "tests-not-changed" for warning in report["warnings"])


def test_diff_context_respects_budget_and_contains_changed_file(tmp_path):
    root = _git_repo(tmp_path)
    (root / "src" / "service.py").write_text(
        "from src.repository import load_user\ndef refresh_session(user_id):\n    return load_user(user_id) or {}\n"
    )
    result = build_diff_context(root, max_tokens=500)
    assert result["estimated_tokens"] <= 500
    assert "src/service.py" in result["review"]["impacts"]


def test_diff_context_with_many_changed_files_still_returns_context(tmp_path):
    # A diff touching hundreds of files/symbols (e.g. a merge commit) used to
    # embed the whole unbounded file/symbol list into the pack header, which
    # by itself exceeded max_tokens and made _fit_section give up and return
    # an empty pack. Guard against that regressing.
    root = _git_repo(tmp_path)
    src = root / "src"
    for i in range(150):
        name = f"generated_module_{i}_with_a_very_long_descriptive_symbol_name_for_query_inflation"
        (src / f"mod_{i}.py").write_text(f"def {name}():\n    return {i}\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    result = build_diff_context(root, staged=True, max_tokens=500)
    assert result["context"].strip()
    assert result["estimated_tokens"] <= 500


def test_persistent_index_service_reuses_then_refreshes_changed_file(tmp_path):
    root = _graph_repo(tmp_path)
    service = IndexService(root)
    first = json.loads(call_tool(root, "index_status", {}, service)["content"][0]["text"])
    assert first["files"] == 3
    (root / "src" / "repository.py").write_text("def load_user(user_id):\n    return None\n")
    refreshed = json.loads(call_tool(root, "refresh_index", {}, service)["content"][0]["text"])
    assert refreshed["reparsed"] == 1
    assert refreshed["reused"] == 2


def test_agent_evaluator_requires_pairs_and_suppresses_claim_without_quality(tmp_path):
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({"runs": [
        {"task": "a", "condition": "baseline", "success": True,
         "input_tokens": 1000, "output_tokens": 100},
        {"task": "a", "condition": "token-saver", "success": False,
         "input_tokens": 300, "output_tokens": 100, "context_failure": True},
    ]}))
    result = evaluate_agent_runs(manifest)
    assert result["quality_parity"] is False
    assert result["tokens_per_success_reduction"] is None
    assert result["claim_allowed"] is False


def test_agent_evaluator_reports_reduction_only_at_quality_parity(tmp_path):
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({"runs": [
        {"task": "a", "condition": "baseline", "success": True,
         "input_tokens": 1000, "output_tokens": 100},
        {"task": "a", "condition": "token-saver", "success": True,
         "input_tokens": 400, "output_tokens": 100},
    ]}))
    result = evaluate_agent_runs(manifest)
    assert result["quality_parity"] is True
    assert result["tokens_per_success_reduction"] == pytest.approx(1 - 500 / 1100)
    assert result["claim_allowed"] is True


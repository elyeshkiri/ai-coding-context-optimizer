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


def test_type_alias_signature_is_truncated_like_a_function_body(tmp_path):
    # type_alias_declaration has no tree-sitter "body" field (unlike
    # functions/classes/interfaces), so its inline right-hand side previously
    # went untruncated into its captured signature -- double-counting every
    # word in it at both the 20x name-term ranking weight (signature) and
    # the 1x body-term weight it already gets like any other symbol's body.
    # Found via the frozen external holdout (colinhacks/zod): a type alias
    # describing a function's return shape outscored the function itself
    # purely because the type's inline object-literal fields happened to
    # lexically match the query.
    source = tmp_path / "errors.ts"
    source.write_text(textwrap.dedent("""
        type FlattenedError<T, U = string> = {
          formErrors: U[];
          fieldErrors: { [P in keyof T]?: U[] };
        };
    """))
    index = build_index(tmp_path, persist=False)
    alias = next(symbol for symbol in index.records["errors.ts"].definitions
                 if symbol.name == "FlattenedError")
    assert "formErrors" not in alias.signature
    assert "fieldErrors" not in alias.signature


def test_member_assignment_function_is_indexed_with_prototype_owner_as_parent(tmp_path):
    # `res.cookie = function (...) {}` / `View.prototype.lookup = function
    # lookup(...) {}` -- the common CommonJS/prototype-assignment pattern
    # for defining a method or export, distinct from `const x =
    # function(){}` (a variable_declarator). tree-sitter gives this its own
    # "assignment_expression" node type with "left"/"right" fields, not
    # "name"/"value", so it was previously invisible to symbol extraction
    # entirely -- found via the second frozen external holdout
    # (expressjs/express, whose entire response.js/request.js public API is
    # written this way). The `.prototype.` form specifically must also
    # record the owning constructor function as `parent`, the same
    # relationship a real class has to its methods, or the constructor's
    # own thin body can be outranked and displaced by one of its own
    # prototype methods in symbol-window selection.
    source = tmp_path / "view.js"
    source.write_text(textwrap.dedent("""
        function View(name, options) {
          this.name = name;
        }

        View.prototype.lookup = function lookup(name) {
          return name;
        }

        exports.etag = function etag(body) {
          return body.length;
        }
    """))
    index = build_index(tmp_path, persist=False)
    definitions = index.records["view.js"].definitions
    lookup = next(symbol for symbol in definitions if symbol.name == "lookup")
    etag = next(symbol for symbol in definitions if symbol.name == "etag")
    assert lookup.parent == "View"
    assert etag.parent is None


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


def test_diff_context_coverage_reports_selected_and_missing_changed_files(tmp_path):
    root = _git_repo(tmp_path)
    (root / "src" / "service.py").write_text(
        "from src.repository import load_user\ndef refresh_session(user_id, force=False):\n    return {**load_user(user_id), 'force': force}\n"
    )
    big = "\n".join(f"def widget_handler_{i}(payload_{i}):\n    return payload_{i}\n" for i in range(200))
    (root / "src" / "big_new_widgets.py").write_text(big)
    subprocess.run(["git", "add", "."], cwd=root, check=True)

    result = build_diff_context(root, staged=True, max_tokens=600)
    coverage = result["coverage"]
    assert coverage["changed_files"] == 2
    assert "src/service.py" in coverage["selected"]
    # Small budget: the big new file is very likely squeezed out, and the
    # manifest must say so explicitly rather than silently drop it.
    if "src/big_new_widgets.py" not in coverage["selected"]:
        assert "src/big_new_widgets.py" in coverage["not_represented"]
    assert coverage["by_category"]["source"]["total"] == 2


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


def test_diff_context_prioritizes_edited_file_over_larger_new_file(tmp_path):
    # A diff mixing a large new file with a small edit to an existing file
    # must not let the new file's BM25 term-overlap (which scales with its
    # size) starve the edit out of the budget -- the edit is where
    # regression risk actually lives.
    root = _git_repo(tmp_path)
    src = root / "src"
    # service.py is already committed by _git_repo; editing it (not adding a
    # new file) is what gives it git status "M".
    (src / "service.py").write_text(
        "from src.repository import load_user\ndef refresh_session(user_id, force=False):\n    return {**load_user(user_id), 'force': force}\n"
    )
    big = "\n".join(f"def widget_handler_{i}(payload_{i}):\n    return payload_{i}\n" for i in range(200))
    (src / "big_new_widgets.py").write_text(big)
    subprocess.run(["git", "add", "."], cwd=root, check=True)

    result = build_diff_context(root, staged=True, max_tokens=600)
    assert "src/service.py" in result["selected_files"]
    assert "force=False" in result["context"]


def test_diff_context_reserves_budget_for_new_database_evidence(tmp_path):
    # A brand-new SQL migration is git status "A" -- the modified-file
    # priority mechanism gives it no help at all, so without a guaranteed
    # per-category reservation it competes on raw BM25 term-overlap against
    # a large new source file and loses outright (this reproduces the real
    # gap found reviewing a production diff: the migration was indexed and
    # searchable but never won the budget competition).
    root = _git_repo(tmp_path)
    (root / "drizzle").mkdir()
    (root / "drizzle" / "0001_experiments.sql").write_text(
        'CREATE TABLE "experiments" (id uuid primary key, variant text);\n'
    )
    big = "\n".join(f"def widget_handler_{i}(payload_{i}):\n    return payload_{i}\n" for i in range(300))
    (root / "src" / "big_new_widgets.py").write_text(big)
    subprocess.run(["git", "add", "."], cwd=root, check=True)

    result = build_diff_context(root, staged=True, max_tokens=800)
    assert "drizzle/0001_experiments.sql" in result["selected_files"]
    coverage = result["coverage"]
    assert coverage["by_category"]["database"]["selected"] == 1


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


def test_agent_evaluator_reports_measurements_but_no_claim_without_blind_quality(tmp_path):
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({"runs": [
        {"task": "a", "condition": "baseline", "success": True,
         "input_tokens": 1000, "output_tokens": 100},
        {"task": "a", "condition": "token-saver", "success": True,
         "input_tokens": 400, "output_tokens": 100},
    ]}))
    result = evaluate_agent_runs(manifest)

    assert result["quality_parity"] is True
    assert result["raw_output_token_reduction"] == pytest.approx(0.0)
    assert result["tokens_per_success_reduction"] == pytest.approx(1 - 500 / 1100)
    assert result["claim_allowed"] is False
    assert "missing_blind_quality_evidence" in result["claim_blockers"]


def test_agent_evaluator_can_gate_savings_on_blind_response_quality(tmp_path):
    quality = {
        "correctness": 5,
        "completeness": 4,
        "actionability": 4,
        "safety": 5,
        "concision": 4,
    }
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({
        "quality_evaluation": {
            "blinded": True,
            "judge": "independent-response-grader",
        },
        "runs": [
            {
                "task": "a", "condition": "baseline", "success": True,
                "input_tokens": 1000, "output_tokens": 400,
                "quality": quality, "blocker": False,
            },
            {
                "task": "a", "condition": "token-saver", "success": True,
                "input_tokens": 700, "output_tokens": 200,
                "quality": {**quality, "concision": 5}, "blocker": False,
            },
        ],
    }))
    result = evaluate_agent_runs(manifest)

    assert result["task_success_parity"] is True
    assert result["quality_parity"] is True
    assert result["quality_evidence"]["blinded"] is True
    assert result["blind_quality_verified"] is True
    assert result["raw_output_token_reduction"] == pytest.approx(0.5)
    assert result["output_tokens_per_success_reduction"] == pytest.approx(0.5)
    assert result["claim_allowed"] is True
    assert result["claim_blockers"] == []


def test_agent_evaluator_suppresses_claim_when_quality_regresses(tmp_path):
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({
        "quality_evaluation": {"blinded": True},
        "runs": [
            {
                "task": "a", "condition": "baseline", "success": True,
                "input_tokens": 1000, "output_tokens": 400,
                "quality": {
                    "correctness": 5, "completeness": 5, "actionability": 4,
                    "safety": 5, "concision": 3,
                },
                "blocker": False,
            },
            {
                "task": "a", "condition": "token-saver", "success": True,
                "input_tokens": 600, "output_tokens": 100,
                "quality": {
                    "correctness": 4, "completeness": 4, "actionability": 4,
                    "safety": 5, "concision": 5,
                },
                "blocker": False,
            },
        ],
    }))
    result = evaluate_agent_runs(manifest)

    assert result["task_success_parity"] is True
    assert result["quality_parity"] is False
    assert result["raw_output_token_reduction"] == pytest.approx(0.75)
    assert result["tokens_per_success_reduction"] == pytest.approx(1 - 700 / 1400)
    assert result["claim_allowed"] is False
    assert "quality_regression" in result["claim_blockers"]



def test_agent_evaluator_supports_multiple_trials_per_task(tmp_path):
    quality = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 4,
    }
    runs = []
    for trial, baseline_output, optimized_output in (
        (1, 400, 200),
        (2, 500, 250),
        (3, 600, 300),
    ):
        runs.extend([
            {
                "task": "auth", "trial": trial, "condition": "baseline",
                "success": True, "input_tokens": 1000,
                "output_tokens": baseline_output, "quality": quality,
                "blocker": False,
            },
            {
                "task": "auth", "trial": trial, "condition": "token-saver",
                "success": True, "input_tokens": 700,
                "output_tokens": optimized_output,
                "quality": {**quality, "concision": 5}, "blocker": False,
            },
        ])
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({
        "quality_evaluation": {"blinded": True, "judge": "grader"},
        "runs": runs,
    }))

    result = evaluate_agent_runs(manifest)

    assert result["tasks"] == 1
    assert result["paired_trials"] == 3
    assert result["conditions"]["baseline"]["runs"] == 3
    assert result["conditions"]["token-saver"]["runs"] == 3
    assert result["output_tokens_per_success_reduction"] == pytest.approx(0.5)
    assert result["paired"]["paired_trial_count"] == 3
    assert result["paired"]["unique_task_count"] == 1
    assert result["paired"]["trials_per_task"] == {"min": 3, "max": 3}
    assert result["paired"]["output_token_reduction"]["mean"] == pytest.approx(0.5)
    assert len(result["paired"]["output_token_reduction"]["mean_ci95"]) == 2
    assert result["claim_allowed"] is True


def test_agent_evaluator_pairs_by_task_trial_and_rejects_duplicate_condition(tmp_path):
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({"runs": [
        {"task": "a", "trial": 1, "condition": "baseline", "success": True},
        {"task": "a", "trial": 1, "condition": "baseline", "success": True},
        {"task": "a", "trial": 1, "condition": "token-saver", "success": True},
    ]}))

    with pytest.raises(ValueError, match="duplicate baseline run for task/trial: a/1"):
        evaluate_agent_runs(manifest)


def test_agent_evaluator_rejects_unblinded_quality_claim(tmp_path):
    quality = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }
    manifest = tmp_path / "runs.json"
    manifest.write_text(json.dumps({
        "quality_evaluation": {"blinded": False},
        "runs": [
            {
                "task": "a", "condition": "baseline", "success": True,
                "input_tokens": 1000, "output_tokens": 400,
                "quality": quality, "blocker": False,
            },
            {
                "task": "a", "condition": "token-saver", "success": True,
                "input_tokens": 700, "output_tokens": 200,
                "quality": quality, "blocker": False,
            },
        ],
    }))

    result = evaluate_agent_runs(manifest)

    assert result["quality_parity"] is True
    assert result["blind_quality_verified"] is False
    assert result["claim_allowed"] is False
    assert "quality_evidence_not_blinded" in result["claim_blockers"]

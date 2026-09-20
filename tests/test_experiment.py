import json
import subprocess
import sys
from pathlib import Path

import pytest

from token_saver.benchmark import evaluate, task_definition_hash
from token_saver.experiment import (
    _expand_command,
    build_schedule,
    prompt_sha256,
    run_experiment,
    validate_suite,
)


def _git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "bench@example.test")
    _git(repo, "config", "user.name", "Benchmark")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _runner(tmp_path):
    script = tmp_path / "runner.py"
    script.write_text(
        """
import json
import pathlib
import sys

transcript = pathlib.Path(sys.argv[1])
condition = sys.argv[2]
model = sys.argv[3]
pathlib.Path("fixed.txt").write_text("ok", encoding="utf-8")
usage = {
    "input_tokens": 100 if condition == "baseline" else 60,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 10,
}
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.write_text(json.dumps({
    "type": "assistant",
    "message": {
        "id": f"{condition}-message",
        "model": model,
        "usage": usage,
        "content": [],
    },
}) + "\\n", encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )
    return script


def _suite(tmp_path, task_count=2, trials=2):
    repo, revision = _repo(tmp_path)
    runner = _runner(tmp_path)
    tasks = []
    for n in range(task_count):
        prompt = f"Fix fixture task {n} and make the independent verifier pass."
        tasks.append({
            "id": f"task-{n}",
            "repository": "fixture",
            "revision": revision,
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "verifier": [[
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('fixed.txt').read_text() == 'ok'",
            ]],
        })
    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-19T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {
            "trials_per_task": trials,
            "condition_order_seed": 1729,
        },
        "repositories": {
            "fixture": {"path": "source", "revision": revision},
        },
        "runner": {
            "command": [
                sys.executable,
                str(runner),
                "{transcript}",
                "{condition}",
                "{model}",
            ],
            "model": "synthetic-test-model",
            "transcript_mode": "path",
            "timeout_seconds": 30,
        },
        "tasks": tasks,
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return path, suite


def test_schedule_is_deterministic_and_balanced(tmp_path):
    path, suite = _suite(tmp_path)
    loaded = validate_suite(path, require_broad=False)

    first = build_schedule(loaded)
    second = build_schedule(loaded)

    assert first == second
    assert len(first) == 2 * 2 * 2
    for task in ("task-0", "task-1"):
        for trial in (1, 2):
            conditions = [
                row["condition"]
                for row in first
                if row["task"] == task and row["trial"] == trial
            ]
            assert sorted(conditions) == ["baseline", "enabled"]


def test_frozen_hash_detects_task_mutation(tmp_path):
    path, suite = _suite(tmp_path)
    payload = json.loads(path.read_text())
    payload["tasks"][0]["prompt"] += " changed"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="prompt_sha256 mismatch"):
        validate_suite(path, require_broad=False)


def test_broad_suite_requires_20_tasks_and_three_trials(tmp_path):
    path, _suite_payload = _suite(tmp_path, task_count=2, trials=2)

    with pytest.raises(ValueError, match="at least 20 tasks"):
        validate_suite(path)


def test_experiment_runs_both_arms_and_independent_verifier(
    tmp_path, monkeypatch
):
    path, _suite_payload = _suite(tmp_path)
    monkeypatch.setattr(
        "token_saver.experiment.user_token_saver_hook_configured",
        lambda: False,
    )
    output = tmp_path / "runs.json"

    result = run_experiment(
        path,
        output,
        allow_development=True,
    )

    assert len(result["runs"]) == 8
    assert all(run["success"] for run in result["runs"])
    assert {run["condition"] for run in result["runs"]} == {"baseline", "enabled"}
    assert all(run["manual_intervention"] is False for run in result["runs"])
    assert all(run["verification"][0]["exit_code"] == 0 for run in result["runs"])
    assert all((tmp_path / run["transcripts"][0]).is_file() for run in result["runs"])
    assert all(run["output_tokens"] == 10 for run in result["runs"])
    assert all(run["model_calls"] == 1 for run in result["runs"])
    assert all(
        run["input_tokens"] == (100 if run["condition"] == "baseline" else 60)
        for run in result["runs"]
    )
    assert all(run["cache_creation_input_tokens"] == 0 for run in result["runs"])
    assert all(run["cache_creation_5m_input_tokens"] == 0 for run in result["runs"])
    assert all(run["cache_creation_1h_input_tokens"] == 0 for run in result["runs"])
    assert all(run["cache_creation_unknown_input_tokens"] == 0 for run in result["runs"])
    assert all(run["cache_read_input_tokens"] == 0 for run in result["runs"])
    assert all(run["tool_calls"] == 0 for run in result["runs"])
    # The synthetic path-mode runner writes a transcript directly and does not
    # execute Claude hooks, so policy telemetry is correctly absent.
    assert all(run["output_policy_telemetry"] is None for run in result["runs"])

    # Re-running resumes from the checkpoint instead of duplicating paid trials.
    resumed = run_experiment(
        path,
        output,
        allow_development=True,
    )
    assert len(resumed["runs"]) == 8


def test_experiment_output_flows_into_transcript_cost_report(
    tmp_path, monkeypatch
):
    path, _suite_payload = _suite(tmp_path)
    monkeypatch.setattr(
        "token_saver.experiment.user_token_saver_hook_configured",
        lambda: False,
    )
    output = tmp_path / "runs.json"
    run_experiment(path, output, allow_development=True)

    rates = tmp_path / "rates.json"
    rates.write_text(json.dumps({
        "synthetic-test-model": {
            "input": 1.0,
            "cache_write_5m": 1.0,
            "cache_write_1h": 1.0,
            "cache_read": 1.0,
            "output": 1.0,
        }
    }), encoding="utf-8")

    report = evaluate(output, rates)

    assert report["paired_trials"] == 4
    assert report["unique_tasks"] == 2
    assert report["results"]["baseline"]["success_rate"] == 1.0
    assert report["results"]["enabled"]["success_rate"] == 1.0
    assert report["comparison"]["delta"]["cost_per_success_reduction"] > 0
    assert report["comparison"]["confidence"]["task_clusters"] == 2
    assert report["evidence"]["protocol_valid"] is False
    assert any(
        "at least 20" in issue or "at least 3" in issue
        for issue in report["evidence"]["protocol_issues"]
    )


def test_hidden_test_patch_is_applied_only_after_agent(tmp_path, monkeypatch):
    repo, revision = _repo(tmp_path)
    runner = tmp_path / "hidden_runner.py"
    runner.write_text(
        """
import json
import pathlib
import sys

assert not pathlib.Path("grader.py").exists(), "hidden grader leaked to agent"
pathlib.Path("fixed.txt").write_text("ok", encoding="utf-8")
transcript = pathlib.Path(sys.argv[1])
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.write_text(json.dumps({
    "type": "assistant",
    "message": {
        "id": "hidden-test",
        "model": "synthetic-test-model",
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 1
        },
        "content": []
    }
}) + "\\n", encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )
    prompt = "Create fixed.txt with the value ok."
    test_patch = """diff --git a/grader.py b/grader.py
new file mode 100644
--- /dev/null
+++ b/grader.py
@@ -0,0 +1,2 @@
+from pathlib import Path
+assert Path("fixed.txt").read_text() == "ok"
"""
    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-19T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {"trials_per_task": 1, "condition_order_seed": 1},
        "repositories": {
            "fixture": {"path": "source", "revision": revision},
        },
        "runner": {
            "command": [
                sys.executable,
                str(runner),
                "{transcript}",
            ],
            "model": "synthetic-test-model",
            "transcript_mode": "path",
            "timeout_seconds": 30,
        },
        "tasks": [{
            "id": "hidden",
            "repository": "fixture",
            "revision": revision,
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "test_patch": test_patch,
            "verifier": [[sys.executable, "grader.py"]],
        }],
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    path = tmp_path / "hidden-suite.json"
    path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "token_saver.experiment.user_token_saver_hook_configured",
        lambda: False,
    )

    result = run_experiment(
        path,
        tmp_path / "hidden-runs.json",
        allow_development=True,
    )

    assert len(result["runs"]) == 2
    assert all(run["success"] for run in result["runs"])
    assert all(
        any(step.get("kind") == "hidden_test_patch" for step in run["verification"])
        for run in result["runs"]
    )


def _expand(command, prompt="fix it"):
    return _expand_command(
        command,
        worktree=Path("/w"),
        transcript=Path("/t.jsonl"),
        prompt=prompt,
        prompt_file=Path("/p.txt"),
        model="m",
        condition="baseline",
    )


def test_expand_command_substitutes_only_known_placeholders():
    assert _expand(["run", "{model}", "{condition}", "{worktree}"]) == [
        "run", "m", "baseline", "/w",
    ]
    assert _expand(["--settings", '{"a": {"b": 1}}']) == ["--settings", '{"a": {"b": 1}}']
    assert _expand(["{unknown}", "x{}y", "{0}"]) == ["{unknown}", "x{}y", "{0}"]


def test_expand_command_does_not_reinterpret_braces_in_substituted_text():
    assert _expand(["{prompt}"], prompt="use {model} and {x}") == ["use {model} and {x}"]
    assert _expand(["{prompt}:{model}"], prompt="{model}") == ["{model}:m"]


def test_agent_runner_failure_is_reported_before_missing_transcript(
    tmp_path, monkeypatch
):
    repo, revision = _repo(tmp_path)
    runner = tmp_path / "failing_runner.py"
    runner.write_text(
        "import sys\nprint('provider rejected request')\n"
        "print('workspace header missing', file=sys.stderr)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    prompt = "Fix the fixture."
    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-19T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {"trials_per_task": 1, "condition_order_seed": 1},
        "repositories": {
            "fixture": {"path": "source", "revision": revision},
        },
        "runner": {
            "command": [sys.executable, str(runner)],
            "model": "synthetic-test-model",
            "transcript_mode": "path",
            "timeout_seconds": 30,
        },
        "tasks": [{
            "id": "runner-failure",
            "repository": "fixture",
            "revision": revision,
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "verifier": [[sys.executable, "-c", "raise SystemExit(0)"]],
        }],
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    path = tmp_path / "failure-suite.json"
    path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "token_saver.experiment.user_token_saver_hook_configured",
        lambda: False,
    )

    with pytest.raises(ValueError) as excinfo:
        run_experiment(
            path,
            tmp_path / "failure-runs.json",
            allow_development=True,
        )
    message = str(excinfo.value)
    assert "agent runner exited 2" in message
    assert "provider rejected request" in message
    assert "workspace header missing" in message
    assert "runner did not create transcript" not in message



def test_condition_profiles_are_frozen_and_exposed_in_dry_run(tmp_path):
    """Session holdouts can install Token Saver in both arms with isolated env switches."""
    path, _suite_payload = _suite(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runner"]["condition_profiles"] = {
        "baseline": {
            "label": "v1.6-session-baseline",
            "install_token_saver": True,
            "env": {"TOKEN_SAVER_EFFICIENCY": "0"},
        },
        "enabled": {
            "label": "v1.7-session-efficiency",
            "install_token_saver": True,
            "env": {"TOKEN_SAVER_EFFICIENCY": "1"},
        },
    }
    payload["protocol"]["task_definition_sha256"] = task_definition_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_experiment(
        path,
        tmp_path / "unused.json",
        dry_run=True,
        allow_development=True,
    )

    assert result["condition_profiles"]["baseline"]["install_token_saver"] is True
    assert result["condition_profiles"]["baseline"]["env"] == {
        "TOKEN_SAVER_EFFICIENCY": "0"
    }
    assert result["condition_profiles"]["enabled"]["label"] == (
        "v1.7-session-efficiency"
    )


def test_condition_profiles_reject_extra_or_missing_arm(tmp_path):
    """A condition-profile experiment must define exactly both randomized arms."""
    path, _suite_payload = _suite(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runner"]["condition_profiles"] = {
        "enabled": {
            "install_token_saver": True,
            "env": {"TOKEN_SAVER_EFFICIENCY": "1"},
        }
    }
    payload["protocol"]["task_definition_sha256"] = task_definition_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly baseline and enabled"):
        validate_suite(path, require_broad=False)

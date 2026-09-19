import json
import subprocess
import sys

import pytest

from token_saver.benchmark import evaluate, task_definition_hash
from token_saver.experiment import (
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

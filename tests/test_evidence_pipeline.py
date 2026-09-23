"""Tests for the resumable one-command evidence pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from acco.benchmark import task_definition_hash
from acco.evidence_pipeline import run_evidence_pipeline
from acco.experiment import prompt_sha256


def _git(repo: Path, *args: str) -> str:
    """Run git in one fixture repository."""
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _suite(tmp_path: Path):
    """Create a three-task synthetic suite with real telemetry-shaped evidence."""
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "bench@example.test")
    _git(repo, "config", "user.name", "Benchmark")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    revision = _git(repo, "rev-parse", "HEAD")

    runner = tmp_path / "runner.py"
    runner.write_text(
        """import json
import os
import pathlib
import sys

transcript = pathlib.Path(sys.argv[1])
condition = sys.argv[2]
model = sys.argv[3]
pathlib.Path("fixed.txt").write_text("ok", encoding="utf-8")
fresh = 100 if condition == "baseline" else 60
usage = {
    "input_tokens": fresh,
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
        "content": [{"type": "text", "text": f"{condition} task completed"}],
    },
}) + "\\n", encoding="utf-8")

if condition == "enabled":
    state = pathlib.Path(os.environ["ACCO_STATE_DIR"])
    telemetry = state / "telemetry" / "synthetic.jsonl"
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    telemetry.write_text(json.dumps({
        "schema": 1,
        "experiment": {
            "task": os.environ["ACCO_BENCHMARK_TASK"],
            "trial": os.environ["ACCO_BENCHMARK_TRIAL"],
            "condition": condition,
        },
        "turn_status": "completed",
        "task": "coding",
        "mode": "normal",
        "selected_budget": 500,
        "adaptive": True,
        "usage_available": True,
        "input_tokens": fresh,
        "cache_creation_input_tokens": 0,
        "cache_creation_5m_input_tokens": 0,
        "cache_creation_1h_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 10,
        "model_calls": 1,
        "budget_utilization": 0.02,
        "target_met": True,
    }) + "\\n", encoding="utf-8")
""",
        encoding="utf-8",
    )

    counter = tmp_path / "grader-count.txt"
    grader = tmp_path / "grader.py"
    grader.write_text(
        """import json
import os
import pathlib
import sys

sys.stdin.read()
counter = pathlib.Path(os.environ["GRADE_COUNTER"])
value = int(counter.read_text() or "0") if counter.exists() else 0
counter.write_text(str(value + 1))
row = {
    "correctness": 5,
    "completeness": 5,
    "actionability": 5,
    "safety": 5,
    "concision": 5,
    "blocker": False,
}
print(json.dumps({"A": row, "B": row}))
""",
        encoding="utf-8",
    )

    tasks = []
    for index in range(3):
        prompt = f"Fix synthetic fixture {index}."
        tasks.append(
            {
                "id": f"task-{index}",
                "repository": "fixture",
                "revision": revision,
                "prompt": prompt,
                "prompt_sha256": prompt_sha256(prompt),
                "verifier": [
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; assert Path('fixed.txt').read_text() == 'ok'",
                    ]
                ],
            }
        )

    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-20T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {"trials_per_task": 1, "condition_order_seed": 9},
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
            "model": "synthetic-model",
            "transcript_mode": "path",
            "timeout_seconds": 30,
        },
        "tasks": tasks,
        "quality_grader": {
            "command": [sys.executable, str(grader)],
            "judge": "synthetic-judge",
            "assignment_seed": 11,
            "timeout_seconds": 30,
            "env": {"GRADE_COUNTER": str(counter)},
        },
        "evidence": {"pricing_file": "rates.json"},
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    (tmp_path / "rates.json").write_text(
        json.dumps(
            {
                "synthetic-model": {
                    "input": 2.0,
                    "cache_write_5m": 3.0,
                    "cache_write_1h": 4.0,
                    "cache_read": 0.5,
                    "output": 6.0,
                }
            }
        ),
        encoding="utf-8",
    )
    return suite_path, counter


def test_evidence_pipeline_runs_grades_reports_calibrates_and_resumes(
    tmp_path, monkeypatch
):
    """One command should compose all evidence stages and reuse checkpoints."""
    suite, counter = _suite(tmp_path)
    monkeypatch.setattr(
        "acco.experiment.user_acco_hook_configured",
        lambda: False,
    )
    runs = tmp_path / "runs.json"

    first = run_evidence_pipeline(
        suite,
        runs,
        allow_development=True,
    )

    assert first["stage"] == "complete"
    assert first["graded_pairs"] == 3
    assert first["claim_allowed"] is False
    assert "insufficient_distinct_tasks" in first["publication_gate"]["blockers"]
    assert counter.read_text() == "3"

    graded = json.loads(runs.read_text(encoding="utf-8"))
    assert all("quality" in run for run in graded["runs"])
    assert all(
        run["output_policy_telemetry"] is not None
        for run in graded["runs"]
        if run["condition"] == "enabled"
    )
    report = json.loads(
        (tmp_path / "runs.effectiveness.json").read_text(encoding="utf-8")
    )
    assert report["telemetry"]["runs_with_policy_telemetry"] == 3
    calibration = json.loads(
        (tmp_path / "runs.output-calibration.json").read_text(encoding="utf-8")
    )
    assert calibration["recommendations"]["coding"]["normal"]["tasks"] == 3

    second = run_evidence_pipeline(
        suite,
        runs,
        allow_development=True,
    )
    assert second["graded_pairs"] == 3
    assert counter.read_text() == "3"


def test_evidence_pipeline_publishable_flag_fails_closed_for_small_suite(
    tmp_path, monkeypatch
):
    """The combined command should expose a nonzero publishability failure."""
    suite, _counter = _suite(tmp_path)
    monkeypatch.setattr(
        "acco.experiment.user_acco_hook_configured",
        lambda: False,
    )

    with pytest.raises(ValueError, match="not publishable"):
        run_evidence_pipeline(
            suite,
            tmp_path / "runs.json",
            allow_development=True,
            require_publishable=True,
        )

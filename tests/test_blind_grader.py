"""Tests for deterministic blind A/B response grading."""

from __future__ import annotations

import json
import sys

import pytest

from acco.blind_grader import blind_grade_manifest


def _transcript(path, text: str) -> None:
    """Write one minimal assistant transcript."""
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": path.stem,
                    "model": "synthetic",
                    "usage": {"output_tokens": 10},
                    "content": [{"type": "text", "text": text}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _manifest(tmp_path, pair_count: int = 2):
    """Build a paired manifest and deterministic grader fixture."""
    counter = tmp_path / "counter.txt"
    grader = tmp_path / "grader.py"
    grader.write_text(
        """import json
import os
import pathlib
import sys

prompt = sys.stdin.read()
assert "condition: baseline" not in prompt.lower()
assert "condition: enabled" not in prompt.lower()
assert "acco" not in prompt.lower()
counter = pathlib.Path(os.environ["GRADE_COUNTER"])
value = int(counter.read_text() or "0") if counter.exists() else 0
counter.write_text(str(value + 1))
print(json.dumps({
    "A": {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
        "blocker": False,
    },
    "B": {
        "correctness": 4,
        "completeness": 4,
        "actionability": 4,
        "safety": 5,
        "concision": 4,
        "blocker": False,
    },
}))
""",
        encoding="utf-8",
    )
    tasks = []
    runs = []
    for index in range(pair_count):
        task_id = f"task-{index}"
        prompt = f"Fix synthetic task {index}."
        tasks.append({"id": task_id, "prompt": prompt})
        baseline_transcript = tmp_path / f"{task_id}-baseline.jsonl"
        enabled_transcript = tmp_path / f"{task_id}-enabled.jsonl"
        _transcript(baseline_transcript, f"baseline response {index}")
        _transcript(enabled_transcript, f"enabled response {index}")
        runs.extend(
            [
                {
                    "task": task_id,
                    "trial": 1,
                    "condition": "baseline",
                    "success": True,
                    "transcripts": [baseline_transcript.name],
                },
                {
                    "task": task_id,
                    "trial": 1,
                    "condition": "enabled",
                    "success": True,
                    "transcripts": [enabled_transcript.name],
                },
            ]
        )
    payload = {
        "tasks": tasks,
        "quality_grader": {
            "command": [sys.executable, str(grader)],
            "judge": "synthetic-blind-judge",
            "assignment_seed": 7,
            "timeout_seconds": 30,
            "env": {"GRADE_COUNTER": str(counter)},
        },
        "runs": runs,
    }
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path, counter


def test_blind_grader_balances_positions_and_maps_scores_back(tmp_path):
    """A/B position randomization should be balanced and condition-hidden."""
    manifest, counter = _manifest(tmp_path, pair_count=4)
    plan = blind_grade_manifest(manifest, dry_run=True)
    result = blind_grade_manifest(manifest)

    assert plan["pairs"] == 4
    assert sorted(row["baseline_label"] for row in plan["plan"]) == ["A", "A", "B", "B"]
    assert result["quality_evaluation"]["blinded"] is True
    assert result["quality_evaluation"]["judge"] == "synthetic-blind-judge"
    assert result["quality_evaluation"]["position_balance"] == {
        "baseline_as_a": 2,
        "baseline_as_b": 2,
    }
    assert counter.read_text() == "4"

    by_pair = {
        (run["task"], run["trial"], run["condition"]): run
        for run in result["runs"]
    }
    for row in plan["plan"]:
        baseline = by_pair[(row["task"], row["trial"], "baseline")]
        enabled = by_pair[(row["task"], row["trial"], "enabled")]
        expected_baseline = 5.0 if row["baseline_label"] == "A" else 4.0
        expected_enabled = 4.0 if row["baseline_label"] == "A" else 5.0
        assert baseline["quality"]["correctness"] == expected_baseline
        assert enabled["quality"]["correctness"] == expected_enabled


def test_blind_grader_resume_does_not_pay_for_completed_pairs(tmp_path):
    """Existing complete grades should be reused without another judge call."""
    manifest, counter = _manifest(tmp_path, pair_count=3)

    first = blind_grade_manifest(manifest)
    second = blind_grade_manifest(manifest)

    assert first["quality_evaluation"]["completed_pairs"] == 3
    assert second["quality_evaluation"]["completed_pairs"] == 3
    assert counter.read_text() == "3"
    assert len(second["blind_grading"]["records"]) == 3


def test_blind_grader_rejects_partial_existing_pair(tmp_path):
    """Half-written quality evidence must fail closed unless explicitly forced."""
    manifest, _counter = _manifest(tmp_path, pair_count=1)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runs"][0]["quality"] = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }
    payload["runs"][0]["blocker"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="partial quality evidence"):
        blind_grade_manifest(manifest)



def test_blind_grader_separate_output_resumes_its_checkpoint(tmp_path):
    """--out should resume the graded destination rather than regrading the source."""
    manifest, counter = _manifest(tmp_path, pair_count=2)
    graded = tmp_path / "graded.json"

    blind_grade_manifest(manifest, output_path=graded)
    blind_grade_manifest(manifest, output_path=graded)

    assert counter.read_text() == "2"
    payload = json.loads(graded.read_text(encoding="utf-8"))
    assert payload["quality_evaluation"]["completed_pairs"] == 2
    assert len(payload["blind_grading"]["records"]) == 2

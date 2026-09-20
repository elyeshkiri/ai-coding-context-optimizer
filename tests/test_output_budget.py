"""Tests for adaptive output budgets and quality-gated calibration."""

from __future__ import annotations

import json

import pytest

from token_saver.command_handlers.output import output_calibrate_main
from token_saver.output_budget import (
    adaptive_output_budget,
    calibrate_output_budgets,
    load_output_calibration,
)


def test_simple_explanation_gets_smaller_bounded_budget():
    """A tiny explanation should not inherit the full generic response budget."""
    decision = adaptive_output_budget(
        "What is Redis?",
        task="explanation",
        mode="normal",
    )

    assert decision.complexity_tier == "simple"
    assert decision.base_tokens == 1000
    assert decision.max_tokens == 700
    assert "simple_explanation" in decision.reasons


def test_broad_multi_part_coding_task_gets_more_budget():
    """Repository-wide multi-part work should receive more room than a tiny edit."""
    prompt = """Implement the repository-wide authentication refactor end-to-end:
- migrate the session API
- update multiple modules
- add integration tests
- update CI and release validation

Also compare the old and new behavior across the repository.
"""
    decision = adaptive_output_budget(prompt, task="coding", mode="normal")

    assert decision.complexity_tier in {"complex", "extended"}
    assert decision.max_tokens > 600
    assert "multi_part_request" in decision.reasons
    assert "broad_scope" in decision.reasons


def test_adaptive_budget_respects_explicit_safety_clamps():
    """Project clamps should win without escaping the mode safety envelope."""
    decision = adaptive_output_budget(
        "Implement a repository-wide migration across multiple modules and tests.",
        task="coding",
        mode="normal",
        min_tokens=500,
        max_tokens=650,
    )

    assert 500 <= decision.max_tokens <= 650


def test_calibration_requires_blind_quality_evidence(tmp_path):
    """Unblinded model grading must never train the budget controller."""
    manifest = tmp_path / "runs.json"
    manifest.write_text(
        json.dumps(
            {
                "quality_evaluation": {"blinded": False},
                "runs": [{"task": "a"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires blinded quality evidence"):
        calibrate_output_budgets(manifest)


def test_calibration_uses_only_successful_quality_preserving_pairs(tmp_path):
    """Cheap failures or degraded responses should not lower learned budgets."""
    quality = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 4,
    }
    runs = []
    for task_id, output_tokens in (
        ("coding-a", 400),
        ("coding-b", 500),
        ("coding-c", 600),
    ):
        runs.extend(
            [
                {
                    "task": task_id,
                    "trial": 1,
                    "condition": "baseline",
                    "success": True,
                    "input_tokens": 1000,
                    "output_tokens": 800,
                    "quality": quality,
                    "blocker": False,
                },
                {
                    "task": task_id,
                    "trial": 1,
                    "condition": "token-saver",
                    "success": True,
                    "input_tokens": 700,
                    "output_tokens": output_tokens,
                    "output_task": "coding",
                    "output_mode": "normal",
                    "quality": quality,
                    "blocker": False,
                },
            ]
        )

    # Very short but lower-quality run: it must not teach the controller.
    runs.extend(
        [
            {
                "task": "bad-shortcut",
                "trial": 1,
                "condition": "baseline",
                "success": True,
                "output_tokens": 800,
                "quality": quality,
                "blocker": False,
            },
            {
                "task": "bad-shortcut",
                "trial": 1,
                "condition": "token-saver",
                "success": True,
                "output_tokens": 50,
                "output_task": "coding",
                "output_mode": "normal",
                "quality": {**quality, "correctness": 3},
                "blocker": False,
            },
        ]
    )

    manifest = tmp_path / "runs.json"
    manifest.write_text(
        json.dumps(
            {
                "quality_evaluation": {"blinded": True, "judge": "grader"},
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )

    result = calibrate_output_budgets(manifest)
    coding = result["recommendations"]["coding"]["normal"]

    assert coding["samples"] == 3
    assert coding["tasks"] == 3
    assert coding["p90_output_tokens"] == pytest.approx(580)
    assert coding["recommended_tokens"] == 667


def test_runtime_can_use_calibrated_base(tmp_path):
    """A valid learned budget should replace the static base before complexity scaling."""
    calibration_path = tmp_path / ".token-saver.output-calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "recommendations": {
                    "coding": {
                        "normal": {
                            "recommended_tokens": 700,
                            "samples": 6,
                            "tasks": 3,
                            "p90_output_tokens": 600,
                            "margin": 1.15,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calibration = load_output_calibration(calibration_path)

    decision = adaptive_output_budget(
        "Implement caching",
        task="coding",
        mode="normal",
        calibration=calibration,
    )

    assert decision.calibrated is True
    assert decision.calibration_samples == 6
    assert decision.base_tokens == 700
    assert decision.max_tokens == 490


def test_output_calibrate_cli_writes_artifact(tmp_path):
    """The CLI should emit a reusable calibration artifact without mutating config."""
    quality = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }
    runs = []
    for task_id, output_tokens in (
        ("review-a", 300),
        ("review-b", 350),
        ("review-c", 400),
    ):
        runs.extend([
            {
                "task": task_id,
                "trial": 1,
                "condition": "baseline",
                "success": True,
                "output_tokens": 600,
                "quality": quality,
                "blocker": False,
            },
            {
                "task": task_id,
                "trial": 1,
                "condition": "token-saver",
                "success": True,
                "output_tokens": output_tokens,
                "output_task": "review",
                "output_mode": "normal",
                "quality": quality,
                "blocker": False,
            },
        ])
    manifest = tmp_path / "runs.json"
    manifest.write_text(
        json.dumps({
            "quality_evaluation": {"blinded": True},
            "runs": runs,
        }),
        encoding="utf-8",
    )
    artifact = tmp_path / "calibration.json"

    assert output_calibrate_main(
        [str(manifest), "--out", str(artifact)]
    ) == 0
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["recommendations"]["review"]["normal"]["samples"] == 3
    assert payload["recommendations"]["review"]["normal"]["tasks"] == 3


def test_calibration_rejects_duplicate_task_trial_condition(tmp_path):
    """Duplicate evidence must fail closed instead of silently replacing a run."""
    quality = {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }
    manifest = tmp_path / "runs.json"
    manifest.write_text(
        json.dumps({
            "quality_evaluation": {"blinded": True},
            "runs": [
                {
                    "task": "a",
                    "trial": 1,
                    "condition": "baseline",
                    "success": True,
                    "quality": quality,
                },
                {
                    "task": "a",
                    "trial": 1,
                    "condition": "baseline",
                    "success": True,
                    "quality": quality,
                },
                {
                    "task": "a",
                    "trial": 1,
                    "condition": "token-saver",
                    "success": True,
                    "output_tokens": 100,
                    "output_task": "coding",
                    "output_mode": "normal",
                    "quality": quality,
                },
            ],
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate baseline calibration run"):
        calibrate_output_budgets(manifest)

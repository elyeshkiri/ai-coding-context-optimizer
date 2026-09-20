"""Tests for joined output-budget effectiveness evidence."""

from __future__ import annotations

import json

import pytest

from token_saver.agent_eval import evaluate_agent_runs
from token_saver.command_handlers.output import output_effectiveness_main
from token_saver.output_effectiveness import (
    EffectivenessPricing,
    evaluate_output_effectiveness,
)


QUALITY = {
    "correctness": 5,
    "completeness": 5,
    "actionability": 5,
    "safety": 5,
    "concision": 4,
}


def _run(task: str, trial: int, condition: str, *, optimized: bool) -> dict:
    """Build one fully measured paired run."""
    fresh = 600 if optimized else 1000
    output = 250 if optimized else 500
    run = {
        "task": task,
        "trial": trial,
        "condition": condition,
        "success": True,
        "manual_intervention": False,
        "model": "synthetic-model",
        "prompt_sha256": f"prompt-{task}",
        "revision": "deadbeef",
        "fresh_input_tokens": fresh,
        "cache_creation_input_tokens": 100 if optimized else 200,
        "cache_read_input_tokens": 300 if optimized else 400,
        "input_tokens": fresh + (100 if optimized else 200) + (300 if optimized else 400),
        "cached_input_tokens": 300 if optimized else 400,
        "output_tokens": output,
        "model_calls": 2,
        "quality": QUALITY,
        "blocker": False,
    }
    if optimized:
        run.update(
            {
                "output_task": "coding",
                "output_mode": "normal",
                "policy_budget": 500,
                "output_policy_telemetry": {
                    "records": 1,
                    "measured_records": 1,
                    "output_task": "coding",
                    "output_mode": "normal",
                    "policy_budget": 500,
                    "selected_budgets": [500],
                    "mean_budget_utilization": 0.5,
                    "target_met_rate": 1.0,
                    "usage_matches_transcript": True,
                },
            }
        )
    return run


def _manifest(path, *, tasks: int, trials: int) -> None:
    """Write a complete blind paired effectiveness manifest."""
    runs = []
    for task_index in range(tasks):
        task = f"task-{task_index}"
        for trial in range(1, trials + 1):
            runs.append(_run(task, trial, "baseline", optimized=False))
            # Raw experiment output uses "enabled"; this is intentional.
            runs.append(_run(task, trial, "enabled", optimized=True))
    path.write_text(
        json.dumps(
            {
                "protocol": {
                    "task_definitions_frozen": True,
                    "condition_order_randomized": True,
                    "independent_verification": True,
                    "history_isolated": True,
                    "hidden_tests_after_agent": True,
                    "frozen_at": "2026-09-20T00:00:00Z",
                    "task_definition_sha256": "a" * 64,
                },
                "quality_evaluation": {
                    "blinded": True,
                    "judge": "independent-grader",
                },
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )


def _pricing() -> EffectivenessPricing:
    """Return deterministic synthetic rates for cost tests."""
    return EffectivenessPricing(
        fresh_input_per_million=2.0,
        cache_creation_per_million=3.0,
        cache_read_per_million=0.5,
        output_per_million=6.0,
    )


def test_effectiveness_joins_enabled_usage_success_quality_and_budget(tmp_path):
    """Real experiment condition names should flow directly into joined evidence."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=3, trials=1)

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    assert result["tasks"] == 3
    assert result["paired_trials"] == 3
    assert result["conditions"]["baseline"]["success_rate"] == 1.0
    assert result["conditions"]["token-saver"]["success_rate"] == 1.0
    assert result["delta"]["cost_per_success_reduction"] > 0
    assert result["quality"]["blinded"] is True
    assert result["quality"]["parity"] is True
    assert result["telemetry"]["runs_with_policy_telemetry"] == 3
    group = result["budget_groups"]["coding:normal:500"]
    assert group["tasks"] == 3
    assert group["quality_safe_rate"] == 1.0
    assert group["eligible_for_calibration"] is True
    assert result["publication_gate"]["passed"] is False
    assert "insufficient_distinct_tasks" in result["publication_gate"]["blockers"]
    assert "insufficient_trials_per_task" in result["publication_gate"]["blockers"]


def test_publishable_effectiveness_requires_full_20_by_3_evidence(tmp_path):
    """Twenty tasks by three trials with parity and positive cost should pass."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    assert result["paired_trials"] == 60
    assert result["protocol"]["valid"] is True
    assert result["publication_gate"]["passed"] is True
    assert result["publication_gate"]["blockers"] == []
    assert result["claim_allowed"] is True
    interval = result["bootstrap"]["cost_per_success_reduction_ci95"]
    assert interval is not None
    assert interval[0] > 0


def test_effectiveness_fails_closed_on_quality_regression(tmp_path):
    """Cheaper output must not become publishable when correctness regresses."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for run in payload["runs"]:
        if run["condition"] == "enabled":
            run["quality"] = {**QUALITY, "correctness": 4}
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    assert result["quality"]["parity"] is False
    assert "quality_regression" in result["publication_gate"]["blockers"]
    assert result["claim_allowed"] is False


def test_effectiveness_fails_closed_on_telemetry_transcript_mismatch(tmp_path):
    """Policy telemetry and copied transcript usage must agree for a cost claim."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runs"][1]["output_policy_telemetry"]["usage_matches_transcript"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    assert result["telemetry"]["usage_mismatches"] == ["task-0/1"]
    assert "telemetry_transcript_usage_mismatch" in result["publication_gate"]["blockers"]


def test_effectiveness_needs_cost_evidence_for_cost_per_success_claim(tmp_path):
    """Token evidence alone should not be relabeled as a dollar-cost claim."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)

    result = evaluate_output_effectiveness(manifest)

    assert result["conditions"]["baseline"]["cost_complete"] is False
    assert result["delta"]["cost_per_success_reduction"] is None
    assert "cost_evidence_incomplete" in result["publication_gate"]["blockers"]


def test_output_effectiveness_cli_enforces_publication_gate(tmp_path, capsys):
    """--require-publishable should return 1 for sound but undersized evidence."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=3, trials=1)

    code = output_effectiveness_main(
        [
            str(manifest),
            "--fresh-input-per-million",
            "2",
            "--cache-creation-per-million",
            "3",
            "--cache-read-per-million",
            "0.5",
            "--output-per-million",
            "6",
            "--json",
            "--require-publishable",
        ]
    )

    assert code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["publication_gate"]["passed"] is False


def test_output_effectiveness_rejects_negative_pricing(tmp_path, capsys):
    """Invalid cost assumptions should fail before producing evidence."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=3, trials=1)

    assert output_effectiveness_main(
        [str(manifest), "--output-per-million", "-1"]
    ) == 2
    assert "pricing values must be nonnegative" in capsys.readouterr().err



def test_agent_evaluate_accepts_raw_experiment_enabled_alias(tmp_path):
    """The established quality evaluator should accept experiment output directly."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=3, trials=1)

    result = evaluate_agent_runs(manifest)

    assert result["tasks"] == 3
    assert result["paired_trials"] == 3
    assert result["task_success_parity"] is True
    assert result["blind_quality_verified"] is True



def test_publishable_gate_rejects_missing_frozen_protocol_even_with_good_metrics(
    tmp_path,
):
    """Good cost/quality numbers are not publishable without frozen experiment design."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.pop("protocol")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    assert result["protocol"]["valid"] is False
    assert (
        "invalid_or_missing_frozen_experiment_protocol"
        in result["publication_gate"]["blockers"]
    )


def test_publishable_gate_requires_ci_to_exclude_zero(tmp_path):
    """A positive point estimate alone is insufficient when task-level variance is wide."""
    manifest = tmp_path / "runs.json"
    _manifest(manifest, tasks=20, trials=3)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    # Make half the optimized tasks materially more expensive while preserving
    # a small positive overall point estimate.
    for run in payload["runs"]:
        if run["condition"] == "enabled" and int(run["task"].split("-")[1]) < 10:
            run["fresh_input_tokens"] = 3000
            run["input_tokens"] = (
                run["fresh_input_tokens"]
                + run["cache_creation_input_tokens"]
                + run["cache_read_input_tokens"]
            )
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_output_effectiveness(manifest, pricing=_pricing())

    interval = result["bootstrap"]["cost_per_success_reduction_ci95"]
    assert result["delta"]["cost_per_success_reduction"] > 0
    assert interval is not None
    assert interval[0] < 0
    assert (
        "cost_per_success_ci_not_strictly_positive"
        in result["publication_gate"]["blockers"]
    )

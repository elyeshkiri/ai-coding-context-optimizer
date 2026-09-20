"""Tests for the frozen session-efficiency publication gate."""

from __future__ import annotations

import hashlib
import json

from token_saver.benchmark import task_definition_hash
from token_saver.output_effectiveness import EffectivenessPricing
from token_saver.session_holdout import evaluate_session_holdout


def _profiles() -> dict:
    """Return the exact isolated session-efficiency arm definitions."""
    return {
        "baseline": {
            "label": "v1.6-session-baseline",
            "install_token_saver": True,
            "env": {
                "TOKEN_SAVER_EFFICIENCY": "0",
                "TOKEN_SAVER_CONTINUITY": "0",
                "TOKEN_SAVER_CROSS_TURN_DEDUP": "0",
                "TOKEN_SAVER_WASTE_DETECTION": "0",
            },
        },
        "enabled": {
            "label": "v1.7-session-efficiency",
            "install_token_saver": True,
            "env": {
                "TOKEN_SAVER_EFFICIENCY": "1",
                "TOKEN_SAVER_CONTINUITY": "1",
                "TOKEN_SAVER_CROSS_TURN_DEDUP": "1",
                "TOKEN_SAVER_WASTE_DETECTION": "1",
            },
        },
    }


def _event_metrics(enabled: bool) -> dict:
    """Return complete treatment/control activation telemetry."""
    return {
        "events": 3 if enabled else 0,
        "continuity_restores": 1 if enabled else 0,
        "dedup_interventions": 1 if enabled else 0,
        "cross_turn_output_dedups": 1 if enabled else 0,
        "unchanged_read_blocks": 0,
        "waste_signals": 1 if enabled else 0,
        "retry_loop_signals": 1 if enabled else 0,
        "repeated_command_signals": 0,
        "tool_cascade_signals": 0,
        "estimated_tool_context_tokens_saved": 100 if enabled else 0,
    }


def _quality() -> dict:
    """Return one blind-quality row."""
    return {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }


def _manifest(path):
    """Write a deterministic publication-grade 20-task × 3-trial fixture."""
    tasks = []
    runs = []
    for task_index in range(20):
        task_id = f"task-{task_index}"
        prompt = f"Fix frozen session task {task_index}."
        tasks.append(
            {
                "id": task_id,
                "repository": "fixture",
                "revision": "deadbeef",
                "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "verifier": [["synthetic-verifier"]],
            }
        )
        for trial in range(1, 4):
            for condition, enabled in (("baseline", False), ("enabled", True)):
                fresh = 700 if enabled else 1000
                output = 80 if enabled else 100
                tools = 7 if enabled else 10
                retries = 1 if enabled else 2
                runs.append(
                    {
                        "task": task_id,
                        "trial": trial,
                        "condition": condition,
                        "condition_label": (
                            "v1.7-session-efficiency"
                            if enabled
                            else "v1.6-session-baseline"
                        ),
                        "revision": "deadbeef",
                        "model": "synthetic-model",
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "success": True,
                        "manual_intervention": False,
                        "fresh_input_tokens": fresh,
                        "cache_creation_input_tokens": 0,
                        "cache_creation_5m_input_tokens": 0,
                        "cache_creation_1h_input_tokens": 0,
                        "cache_creation_unknown_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "input_tokens": fresh,
                        "output_tokens": output,
                        "tool_calls": tools,
                        "model_calls": 2,
                        "seconds": 1.0,
                        "session_metrics": {
                            "tool_calls": tools,
                            "bash_calls": 4 if enabled else 6,
                            "unique_bash_commands": 4,
                            "repeat_command_calls": 1 if enabled else 2,
                            "retry_attempts": retries,
                            "duplicate_read_calls": 1 if enabled else 2,
                        },
                        "session_efficiency_telemetry": _event_metrics(enabled),
                        "quality": _quality(),
                        "blocker": False,
                    }
                )

    payload = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "session_efficiency_isolated": True,
            "frozen_at": "2026-09-20T15:45:00+02:00",
            "task_definition_sha256": "",
        },
        "design": {
            "trials_per_task": 3,
            "condition_order_seed": 20260920,
            "comparison": "v1.6-session-baseline-vs-v1.7-session-efficiency",
            "causal_scope": "combined-session-efficiency-bundle",
        },
        "repositories": {
            "fixture": {"path": ".", "revision": "deadbeef"},
        },
        "runner": {
            "command": [
                "python",
                "-m",
                "token_saver.session_holdout_docker",
                "--condition",
                "{condition}",
            ],
            "model": "synthetic-model",
            "transcript_mode": "path",
            "session_holdout_protocol_version": 1,
            "forced_fresh_session_boundary": True,
            "phase1_mode": "investigation-no-edit",
            "phase1_turns": 12,
            "phase2_mode": "fresh-session-implementation",
            "phase2_turns": 50,
            "continuity_source": "SessionStart:resume",
            "condition_profiles": _profiles(),
        },
        "tasks": tasks,
        "quality_evaluation": {
            "blinded": True,
            "judge": "synthetic-independent-judge",
        },
        "runs": runs,
    }
    payload["protocol"]["task_definition_sha256"] = task_definition_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _pricing() -> EffectivenessPricing:
    """Return complete deterministic token prices."""
    return EffectivenessPricing(
        fresh_input_per_million=2.0,
        cache_creation_5m_per_million=2.5,
        cache_creation_1h_per_million=4.0,
        cache_read_per_million=0.2,
        output_per_million=10.0,
    )


def test_session_holdout_can_pass_full_publication_gate(tmp_path):
    """A broad isolated fixture with positive clustered effect should publish."""
    path = tmp_path / "runs.json"
    _manifest(path)

    report = evaluate_session_holdout(path, pricing=_pricing())

    assert report["tasks"] == 20
    assert report["paired_trials"] == 60
    assert report["reductions"]["tool_calls"] == 0.3
    assert report["reductions"]["input_tokens"] == 0.3
    assert report["reductions"]["retry_attempts"] == 0.5
    assert report["reductions"]["cost_per_success"] > 0
    assert report["bootstrap"]["intervals"]["cost_per_success_usd"][0] > 0
    assert report["feature_activation"]["treatment"][
        "all_feature_families_observed"
    ] is True
    assert report["feature_activation"]["control"]["totals"]["events"] == 0
    assert report["quality"]["blind_quality_verified"] is True
    assert report["publication_gate"] == {"passed": True, "blockers": []}


def test_session_holdout_rejects_control_instrumentation(tmp_path):
    """The causal control must emit no session-efficiency interventions."""
    path = tmp_path / "runs.json"
    payload = _manifest(path)
    baseline = next(run for run in payload["runs"] if run["condition"] == "baseline")
    baseline["session_efficiency_telemetry"]["events"] = 1
    baseline["session_efficiency_telemetry"]["dedup_interventions"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_session_holdout(path, pricing=_pricing())

    assert "control_session_efficiency_not_disabled" in report[
        "publication_gate"
    ]["blockers"]


def test_session_holdout_requires_forced_continuity_activation(tmp_path):
    """A continuity claim must fail if the forced resume hook did not fire."""
    path = tmp_path / "runs.json"
    payload = _manifest(path)
    for run in payload["runs"]:
        if run["condition"] == "enabled":
            run["session_efficiency_telemetry"]["continuity_restores"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_session_holdout(path, pricing=_pricing())

    blockers = report["publication_gate"]["blockers"]
    assert "forced_continuity_restore_missing" in blockers
    assert "session_feature_coverage_incomplete" in blockers


def test_session_holdout_rejects_nonisolated_profile_change(tmp_path):
    """Only the four session switches may differ between experiment arms."""
    path = tmp_path / "runs.json"
    payload = _manifest(path)
    payload["runner"]["condition_profiles"]["enabled"]["env"][
        "UNRELATED_SETTING"
    ] = "different"
    payload["protocol"]["task_definition_sha256"] = task_definition_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_session_holdout(path, pricing=_pricing())

    assert "invalid_or_unfrozen_session_protocol" in report[
        "publication_gate"
    ]["blockers"]
    assert "non_efficiency_condition_env_diff" in report["protocol"]["issues"]

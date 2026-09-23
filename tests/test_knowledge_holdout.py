"""Tests for the frozen knowledge-assisted read-avoidance holdout."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from acco.benchmark import task_definition_hash
from acco.experiment import validate_suite
from acco.knowledge_holdout import (
    evaluate_knowledge_holdout,
    validate_knowledge_holdout_definition,
)
from acco.knowledge_holdout_pipeline import run_knowledge_holdout
from acco.output_effectiveness import EffectivenessPricing
from acco.knowledge_holdout_docker import (
    _PHASE1_PREFIX,
    _knowledge_seed_count,
)

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "benchmarks" / "knowledge-efficiency-swebench-24.frozen.json"


def test_frozen_knowledge_holdout_definition_is_valid():
    """The checked-in 24-task definition should be sealed and arm-isolated."""
    payload = json.loads(FROZEN.read_text(encoding="utf-8"))

    result = validate_knowledge_holdout_definition(payload)

    assert result["valid"] is True
    assert result["frozen"] is True
    assert len(payload["tasks"]) == 24
    assert payload["design"]["trials_per_task"] == 3
    assert result["comparison"]["baseline"] == "knowledge-memory-control"


def test_profile_gate_rejects_unrelated_condition_difference():
    """Only the declared knowledge/cache switches may differ between arms."""
    payload = json.loads(FROZEN.read_text(encoding="utf-8"))
    changed = deepcopy(payload)
    changed["runner"]["condition_profiles"]["enabled"]["env"]["UNRELATED"] = "1"

    with pytest.raises(ValueError, match="non_knowledge_condition_env_diff"):
        validate_knowledge_holdout_definition(changed, require_frozen=False)


def test_phase1_contract_requires_explicit_verified_findings():
    """The benchmark should measure explicit memory, not hidden auto-harvesting."""
    assert "acco remember" in _PHASE1_PREFIX
    assert "VERIFIED project findings" in _PHASE1_PREFIX
    assert "Do not store guesses" in _PHASE1_PREFIX


def test_knowledge_seed_count_reads_isolated_state(tmp_path):
    """Runner exposure evidence should count verified non-superseded findings."""
    directory = tmp_path / "knowledge"
    directory.mkdir()
    (directory / "project.json").write_text(
        json.dumps(
            {
                "findings": [
                    {"confidence": "verified"},
                    {"confidence": "probable"},
                    {"confidence": "verified", "superseded_by": "new"},
                    {"confidence": "verified"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _knowledge_seed_count(tmp_path) == 2



def _profiles() -> dict:
    """Return exact isolated memory-control and knowledge-treatment profiles."""
    common = {
        "ACCO_EFFICIENCY": "1",
        "ACCO_CONTINUITY": "0",
        "ACCO_CROSS_TURN_DEDUP": "0",
        "ACCO_WASTE_DETECTION": "0",
    }
    return {
        "baseline": {
            "label": "knowledge-memory-control",
            "install_acco": True,
            "env": {
                **common,
                "ACCO_KNOWLEDGE_READ_AVOIDANCE": "0",
                "ACCO_CACHE_ECONOMICS": "0",
            },
        },
        "enabled": {
            "label": "knowledge-read-avoidance-cache-economics",
            "install_acco": True,
            "env": {
                **common,
                "ACCO_KNOWLEDGE_READ_AVOIDANCE": "1",
                "ACCO_CACHE_ECONOMICS": "1",
            },
        },
    }


def _quality() -> dict:
    """Return one blind-quality row at exact parity."""
    return {
        "correctness": 5,
        "completeness": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
    }


def _telemetry(enabled: bool) -> dict:
    """Return explicit seed plus treatment-only read-avoidance exposure."""
    return {
        "events": 2 if enabled else 1,
        "knowledge_seed_findings": 2,
        "knowledge_read_avoidance": 1 if enabled else 0,
        "cache_economic_read_avoidance": 1 if enabled else 0,
        "estimated_tool_context_tokens_saved": 300 if enabled else 0,
    }


def _publication_manifest(path: Path) -> dict:
    """Write a deterministic 20-task × 3-trial publishable synthetic fixture."""
    tasks = []
    runs = []
    for task_index in range(20):
        task_id = f"knowledge-task-{task_index}"
        prompt = f"Fix frozen knowledge task {task_index}."
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        tasks.append(
            {
                "id": task_id,
                "repository": "fixture",
                "revision": "deadbeef",
                "prompt": prompt,
                "prompt_sha256": prompt_hash,
                "verifier": [["synthetic-verifier"]],
            }
        )
        for trial in range(1, 4):
            for condition, enabled in (("baseline", False), ("enabled", True)):
                fresh = 700 if enabled else 1000
                output = 80 if enabled else 100
                tools = 7 if enabled else 10
                runs.append(
                    {
                        "task": task_id,
                        "trial": trial,
                        "condition": condition,
                        "condition_label": (
                            "knowledge-read-avoidance-cache-economics"
                            if enabled
                            else "knowledge-memory-control"
                        ),
                        "revision": "deadbeef",
                        "model": "synthetic-model",
                        "prompt_sha256": prompt_hash,
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
                            "bash_calls": 4,
                            "unique_bash_commands": 4,
                            "repeat_command_calls": 0,
                            "retry_attempts": 0,
                            "duplicate_read_calls": 1 if enabled else 3,
                        },
                        "session_efficiency_telemetry": _telemetry(enabled),
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
            "knowledge_efficiency_isolated": True,
            "frozen_at": "2026-09-20T19:15:00+02:00",
            "task_definition_sha256": "",
        },
        "design": {
            "trials_per_task": 3,
            "condition_order_seed": 20260920,
            "comparison": (
                "knowledge-memory-control-vs-"
                "knowledge-read-avoidance-cache-economics"
            ),
            "causal_scope": "knowledge-read-avoidance-plus-cache-economics-gate",
        },
        "repositories": {
            "fixture": {"path": ".", "revision": "deadbeef"},
        },
        "runner": {
            "command": [
                "python",
                "-m",
                "acco.knowledge_holdout_docker",
                "--condition",
                "{condition}",
            ],
            "model": "synthetic-model",
            "transcript_mode": "path",
            "knowledge_holdout_protocol_version": 1,
            "forced_fresh_session_boundary": True,
            "phase1_mode": "investigation-explicit-knowledge-seed",
            "phase1_turns": 14,
            "phase2_mode": "fresh-session-implementation",
            "phase2_turns": 50,
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
    """Return complete deterministic cache-aware pricing."""
    return EffectivenessPricing(
        fresh_input_per_million=2.0,
        cache_creation_5m_per_million=2.5,
        cache_creation_1h_per_million=4.0,
        cache_read_per_million=0.2,
        output_per_million=10.0,
    )


def test_knowledge_holdout_can_pass_full_publication_gate(tmp_path):
    """A broad paired fixture with verified exposure and quality should publish."""
    manifest = tmp_path / "runs.json"
    _publication_manifest(manifest)

    report = evaluate_knowledge_holdout(manifest, pricing=_pricing())

    assert report["tasks"] == 20
    assert report["paired_trials"] == 60
    assert report["reductions"]["tool_calls"] == pytest.approx(0.3)
    assert report["reductions"]["input_tokens"] == pytest.approx(0.3)
    assert report["reductions"]["duplicate_read_calls"] == pytest.approx(2 / 3)
    assert report["reductions"]["cost_per_success"] > 0
    assert report["bootstrap"]["intervals"]["cost_per_success_usd"][0] > 0
    assert report["feature_activation"]["control"]["active_runs"][
        "knowledge_seed"
    ] == 60
    assert report["feature_activation"]["control"]["active_runs"][
        "knowledge_read_avoidance"
    ] == 0
    assert report["feature_activation"]["treatment"]["active_runs"][
        "knowledge_read_avoidance"
    ] == 60
    assert report["quality"]["blind_quality_verified"] is True
    assert report["publication_gate"] == {"passed": True, "blockers": []}


def test_knowledge_holdout_rejects_control_read_avoidance(tmp_path):
    """Control contamination must block a causal knowledge-efficiency claim."""
    manifest = tmp_path / "runs.json"
    payload = _publication_manifest(manifest)
    baseline = next(run for run in payload["runs"] if run["condition"] == "baseline")
    baseline["session_efficiency_telemetry"]["knowledge_read_avoidance"] = 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_knowledge_holdout(manifest, pricing=_pricing())

    assert "control_knowledge_read_avoidance_not_disabled" in report[
        "publication_gate"
    ]["blockers"]


def test_checked_in_knowledge_holdout_pipeline_dry_run_needs_no_external_repos(
    tmp_path,
):
    """Preflight should validate the frozen schedule before paid setup."""
    suite = validate_suite(FROZEN, require_frozen=True, require_broad=True)

    result = run_knowledge_holdout(
        FROZEN,
        tmp_path / "runs.json",
        dry_run=True,
    )

    assert suite["protocol"]["task_definition_sha256"] == (
        "4cb4bc9a05f45666fc1fc013c1a3d29ffd180704c9ac225fd4b7c38ff48fe708"
    )
    assert result["stage"] == "dry-run"
    assert result["experiment"]["task_count"] == 24
    assert result["experiment"]["paired_trials"] == 72
    assert result["experiment"]["run_count"] == 144
    assert result["comparison"] == {
        "baseline": "knowledge-memory-control",
        "treatment": "knowledge-read-avoidance-cache-economics",
    }


def test_paid_knowledge_workflow_requires_explicit_confirmation():
    """The expensive workflow must remain manual and preflight the frozen suite."""
    workflow = (
        ROOT / ".github" / "workflows" / "knowledge-efficiency-holdout.yml"
    ).read_text(encoding="utf-8")

    assert "RUN_KNOWLEDGE_288" in workflow
    assert "knowledge-efficiency-swebench-24.frozen.json" in workflow
    assert "knowledge-holdout-evaluate" in workflow
    assert "Require publication gate" in workflow

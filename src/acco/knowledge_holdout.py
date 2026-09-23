"""Evaluate frozen knowledge-assisted read-avoidance experiments."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from .agent_eval import evaluate_agent_runs
from .benchmark import (
    MIN_PUBLISHABLE_TASKS,
    MIN_PUBLISHABLE_TRIALS_PER_TASK,
    task_definition_hash,
)
from .output_effectiveness import EffectivenessPricing
from .paired_conditions import (
    BASELINE_CONDITION,
    OPTIMIZED_CONDITION,
    normalize_condition,
)
from .session_holdout import (
    _bootstrap,
    _condition_summary,
    _number,
    _reduction,
    _session_metrics,
    _usage,
)

_REQUIRED_CONTROL_ENV = {
    "ACCO_EFFICIENCY": "1",
    "ACCO_CONTINUITY": "0",
    "ACCO_CROSS_TURN_DEDUP": "0",
    "ACCO_WASTE_DETECTION": "0",
    "ACCO_KNOWLEDGE_READ_AVOIDANCE": "0",
    "ACCO_CACHE_ECONOMICS": "0",
}
_REQUIRED_TREATMENT_ENV = {
    "ACCO_EFFICIENCY": "1",
    "ACCO_CONTINUITY": "0",
    "ACCO_CROSS_TURN_DEDUP": "0",
    "ACCO_WASTE_DETECTION": "0",
    "ACCO_KNOWLEDGE_READ_AVOIDANCE": "1",
    "ACCO_CACHE_ECONOMICS": "1",
}


def _profile_installed(profile: dict) -> bool:
    """Return whether an ACCO condition profile installs ACCO."""
    return profile.get("install_acco") is True



def _knowledge_metrics(run: dict) -> dict:
    """Validate intervention telemetry used only for feature-exposure evidence."""
    telemetry = run.get("session_efficiency_telemetry")
    if not isinstance(telemetry, dict):
        raise ValueError("every run requires session_efficiency_telemetry")
    result = {}
    for name in (
        "events",
        "knowledge_seed_findings",
        "knowledge_read_avoidance",
        "cache_economic_read_avoidance",
        "estimated_tool_context_tokens_saved",
    ):
        result[name] = int(
            _number(
                telemetry.get(name, 0),
                f"session_efficiency_telemetry.{name}",
            )
        )
    return result


def _profile_gate(payload: dict) -> tuple[bool, list[str]]:
    """Verify that arms differ only by the frozen knowledge/cache switches."""
    issues: list[str] = []
    runner = payload.get("runner")
    profiles = runner.get("condition_profiles") if isinstance(runner, dict) else None
    if not isinstance(profiles, dict) or set(profiles) != {"baseline", "enabled"}:
        return False, ["missing_knowledge_condition_profiles"]
    baseline = profiles["baseline"]
    enabled = profiles["enabled"]
    if not isinstance(baseline, dict) or not isinstance(enabled, dict):
        return False, ["invalid_knowledge_condition_profiles"]
    if not _profile_installed(baseline):
        issues.append("control_does_not_install_acco")
    if not _profile_installed(enabled):
        issues.append("treatment_does_not_install_acco")
    if str(baseline.get("label") or "") != "knowledge-memory-control":
        issues.append("control_label_mismatch")
    if str(enabled.get("label") or "") != "knowledge-read-avoidance-cache-economics":
        issues.append("treatment_label_mismatch")

    baseline_env = baseline.get("env")
    enabled_env = enabled.get("env")
    if not isinstance(baseline_env, dict) or not isinstance(enabled_env, dict):
        issues.append("condition_env_missing")
    else:
        for key, expected in _REQUIRED_CONTROL_ENV.items():
            if baseline_env.get(key) != expected:
                issues.append(f"control_env_mismatch:{key}")
        for key, expected in _REQUIRED_TREATMENT_ENV.items():
            if enabled_env.get(key) != expected:
                issues.append(f"treatment_env_mismatch:{key}")
        controlled = set(_REQUIRED_CONTROL_ENV)
        control_other = {
            key: value for key, value in baseline_env.items() if key not in controlled
        }
        treatment_other = {
            key: value for key, value in enabled_env.items() if key not in controlled
        }
        if control_other != treatment_other:
            issues.append("non_knowledge_condition_env_diff")

    command = runner.get("command") if isinstance(runner, dict) else None
    if (
        not isinstance(command, list)
        or "acco.knowledge_holdout_docker" not in command
    ):
        issues.append("knowledge_holdout_runner_missing")
    if not isinstance(runner, dict) or runner.get("knowledge_holdout_protocol_version") != 1:
        issues.append("knowledge_holdout_protocol_version_mismatch")
    elif runner.get("forced_fresh_session_boundary") is not True:
        issues.append("fresh_session_boundary_not_forced")
    elif runner.get("phase1_mode") != "investigation-explicit-knowledge-seed":
        issues.append("phase1_mode_mismatch")
    elif runner.get("phase2_mode") != "fresh-session-implementation":
        issues.append("phase2_mode_mismatch")
    return not issues, issues


def _protocol_gate(payload: dict) -> tuple[bool, list[str]]:
    """Verify frozen task identity and the knowledge-efficiency protocol."""
    issues: list[str] = []
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        return False, ["missing_protocol"]
    for key in (
        "task_definitions_frozen",
        "condition_order_randomized",
        "independent_verification",
        "history_isolated",
        "hidden_tests_after_agent",
        "knowledge_efficiency_isolated",
    ):
        if protocol.get(key) is not True:
            issues.append(f"protocol_not_true:{key}")
    if not isinstance(protocol.get("frozen_at"), str) or not protocol["frozen_at"].strip():
        issues.append("missing_frozen_at")
    declared = str(protocol.get("task_definition_sha256") or "").strip()
    try:
        computed = task_definition_hash(payload)
    except ValueError:
        computed = ""
    if not declared or declared != computed:
        issues.append("task_definition_hash_mismatch")
    _profiles_ok, profile_issues = _profile_gate(payload)
    issues.extend(profile_issues)
    return not issues, issues


def validate_knowledge_holdout_definition(
    payload: dict,
    *,
    require_frozen: bool = True,
) -> dict:
    """Validate knowledge/cache arm isolation before any paid run starts."""
    valid, issues = _protocol_gate(payload) if require_frozen else _profile_gate(payload)
    if not require_frozen:
        protocol = payload.get("protocol")
        if (
            not isinstance(protocol, dict)
            or protocol.get("knowledge_efficiency_isolated") is not True
        ):
            issues.append("protocol_not_true:knowledge_efficiency_isolated")
            valid = False
    if not valid:
        raise ValueError(
            "invalid knowledge-efficiency holdout definition: "
            + ", ".join(issues)
        )
    protocol = payload.get("protocol")
    return {
        "valid": True,
        "frozen": require_frozen,
        "task_definition_sha256": (
            protocol.get("task_definition_sha256")
            if isinstance(protocol, dict)
            else None
        ),
        "comparison": {
            "baseline": "knowledge-memory-control",
            "treatment": "knowledge-read-avoidance-cache-economics",
        },
    }


def _activation(runs: list[dict]) -> dict:
    """Summarize knowledge/cache exposure without treating it as outcome truth."""
    totals = defaultdict(int)
    seeded_runs = 0
    avoidance_runs = 0
    cache_economic_runs = 0
    for run in runs:
        metrics = _knowledge_metrics(run)
        for key, value in metrics.items():
            totals[key] += value
        seeded_runs += metrics["knowledge_seed_findings"] > 0
        avoidance_runs += metrics["knowledge_read_avoidance"] > 0
        cache_economic_runs += metrics["cache_economic_read_avoidance"] > 0
    return {
        "totals": dict(sorted(totals.items())),
        "active_runs": {
            "knowledge_seed": seeded_runs,
            "knowledge_read_avoidance": avoidance_runs,
            "cache_economics": cache_economic_runs,
        },
    }


def evaluate_knowledge_holdout(
    path: Path,
    *,
    pricing: EffectivenessPricing,
) -> dict:
    """Evaluate paired fresh-session memory-control vs read-avoidance runs."""
    pricing.validate()
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("knowledge holdout requires a non-empty runs list")

    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    trials_by_task: dict[str, set[int]] = defaultdict(set)
    manual_intervention = False
    identity_issues: list[str] = []
    for raw in runs:
        if not isinstance(raw, dict):
            raise ValueError("every knowledge holdout run must be an object")
        task = str(raw.get("task") or "").strip()
        condition = normalize_condition(raw.get("condition"))
        trial = raw.get("trial", 1)
        if (
            not task
            or condition not in {BASELINE_CONDITION, OPTIMIZED_CONDITION}
            or isinstance(trial, bool)
            or not isinstance(trial, int)
            or trial <= 0
        ):
            raise ValueError("every run requires task, positive trial, and paired condition")
        if not isinstance(raw.get("success"), bool):
            raise ValueError(f"success must be boolean: {task}/{trial}/{condition}")
        _usage(raw)
        _session_metrics(raw)
        _knowledge_metrics(raw)
        pair = grouped.setdefault((task, trial), {})
        if condition in pair:
            raise ValueError(f"duplicate run: {task}/{trial}/{condition}")
        run = dict(raw)
        run["condition"] = condition
        pair[condition] = run
        trials_by_task[task].add(trial)
        intervention = raw.get("manual_intervention", False)
        if not isinstance(intervention, bool):
            raise ValueError("manual_intervention must be boolean")
        manual_intervention = manual_intervention or intervention

    incomplete = [
        f"{task}/{trial}"
        for (task, trial), pair in sorted(grouped.items())
        if set(pair) != {BASELINE_CONDITION, OPTIMIZED_CONDITION}
    ]
    if incomplete:
        raise ValueError("unpaired knowledge holdout trials: " + ", ".join(incomplete))

    pairs = [
        (pair[BASELINE_CONDITION], pair[OPTIMIZED_CONDITION])
        for pair in grouped.values()
    ]
    for baseline, enabled in pairs:
        label = f"{baseline['task']}/{baseline['trial']}"
        for field in ("model", "prompt_sha256", "revision"):
            if not baseline.get(field) or not enabled.get(field):
                identity_issues.append(f"{label}:missing:{field}")
            elif baseline[field] != enabled[field]:
                identity_issues.append(f"{label}:mismatch:{field}")

    baseline_runs = [pair[0] for pair in pairs]
    enabled_runs = [pair[1] for pair in pairs]
    baseline = _condition_summary(baseline_runs, pricing)
    enabled = _condition_summary(enabled_runs, pricing)
    agent = evaluate_agent_runs(path)
    protocol_valid, protocol_issues = _protocol_gate(payload)
    baseline_activation = _activation(baseline_runs)
    activation = _activation(enabled_runs)
    bootstrap = _bootstrap(pairs, pricing)

    reductions = {
        "tool_calls": _reduction(baseline["tool_calls"], enabled["tool_calls"]),
        "input_tokens": _reduction(baseline["input_tokens"], enabled["input_tokens"]),
        "duplicate_read_calls": _reduction(
            baseline["duplicate_read_calls"],
            enabled["duplicate_read_calls"],
        ),
        "cost_per_success": _reduction(
            baseline["cost_per_success_usd"],
            enabled["cost_per_success_usd"],
        ),
    }

    trial_counts = [len(values) for values in trials_by_task.values()]
    blockers: list[str] = []
    if len(trials_by_task) < MIN_PUBLISHABLE_TASKS:
        blockers.append("insufficient_distinct_tasks")
    if min(trial_counts) < MIN_PUBLISHABLE_TRIALS_PER_TASK:
        blockers.append("insufficient_trials_per_task")
    if not protocol_valid:
        blockers.append("invalid_or_unfrozen_knowledge_protocol")
    if identity_issues:
        blockers.append("paired_run_identity_mismatch")
    if manual_intervention:
        blockers.append("manual_intervention_present")
    if not agent["task_success_parity"]:
        blockers.append("task_success_regression")
    if not agent["blind_quality_verified"]:
        blockers.append("blind_quality_not_verified")
    if not baseline["cost_complete"] or not enabled["cost_complete"]:
        blockers.append("cost_evidence_incomplete")

    expected_runs = len(enabled_runs)
    if baseline_activation["active_runs"]["knowledge_seed"] < expected_runs:
        blockers.append("control_knowledge_seed_missing")
    if activation["active_runs"]["knowledge_seed"] < expected_runs:
        blockers.append("treatment_knowledge_seed_missing")
    if baseline_activation["totals"].get("knowledge_read_avoidance", 0) != 0:
        blockers.append("control_knowledge_read_avoidance_not_disabled")
    if baseline_activation["totals"].get("cache_economic_read_avoidance", 0) != 0:
        blockers.append("control_cache_economics_not_disabled")
    if activation["totals"].get("knowledge_read_avoidance", 0) <= 0:
        blockers.append("knowledge_read_avoidance_not_observed")
    if activation["totals"].get("cache_economic_read_avoidance", 0) <= 0:
        blockers.append("cache_economics_not_observed")

    cost_reduction = reductions["cost_per_success"]
    if cost_reduction is None or cost_reduction <= 0:
        blockers.append("no_positive_cost_per_success_reduction")
    interval = bootstrap["intervals"]["cost_per_success_usd"]
    if interval is None or interval[0] <= 0:
        blockers.append("cost_per_success_ci_not_strictly_positive")

    return {
        "schema": 1,
        "comparison": {
            "baseline": "knowledge-memory-control",
            "treatment": "knowledge-read-avoidance-cache-economics",
            "causal_scope": "knowledge_read_avoidance_plus_cache_gate",
        },
        "tasks": len(trials_by_task),
        "paired_trials": len(pairs),
        "trials_per_task": {
            "min": min(trial_counts),
            "max": max(trial_counts),
        },
        "conditions": {
            "baseline": baseline,
            "knowledge-efficiency": enabled,
        },
        "reductions": reductions,
        "bootstrap": bootstrap,
        "feature_activation": {
            "treatment": activation,
            "control": baseline_activation,
        },
        "quality": {
            "task_success_parity": agent["task_success_parity"],
            "quality_parity": agent["quality_parity"],
            "blind_quality_verified": agent["blind_quality_verified"],
            "quality_evidence": agent["quality_evidence"],
        },
        "protocol": {
            "valid": protocol_valid,
            "issues": protocol_issues,
            "paired_identity_issues": identity_issues,
            "task_definition_sha256": (
                payload.get("protocol", {}).get("task_definition_sha256")
                if isinstance(payload.get("protocol"), dict)
                else None
            ),
        },
        "publication_gate": {
            "passed": not blockers,
            "blockers": blockers,
        },
        "claim_allowed": not blockers,
    }

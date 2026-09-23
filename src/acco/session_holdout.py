"""Evaluate the frozen session-efficiency holdout without self-grading behavior."""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import random

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

_BOOTSTRAP_SEED = 271828
_BOOTSTRAP_SAMPLES = 2000
_REQUIRED_CONTROL_ENV = {
    "ACCO_EFFICIENCY": "0",
    "ACCO_CONTINUITY": "0",
    "ACCO_CROSS_TURN_DEDUP": "0",
    "ACCO_WASTE_DETECTION": "0",
}
_REQUIRED_TREATMENT_ENV = {
    "ACCO_EFFICIENCY": "1",
    "ACCO_CONTINUITY": "1",
    "ACCO_CROSS_TURN_DEDUP": "1",
    "ACCO_WASTE_DETECTION": "1",
}


def _profile_installed(profile: dict) -> bool:
    """Return whether an ACCO condition profile installs ACCO."""
    return profile.get("install_acco") is True



def _number(value: object, name: str) -> float:
    """Validate one finite nonnegative numeric field."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a nonnegative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a nonnegative number")
    return number


def _usage(run: dict) -> dict:
    """Return exact cache-TTL-aware billing fields for one run."""
    created = int(_number(run.get("cache_creation_input_tokens", 0), "cache_creation_input_tokens"))
    five = int(_number(run.get("cache_creation_5m_input_tokens", 0), "cache_creation_5m_input_tokens"))
    one_hour = int(_number(run.get("cache_creation_1h_input_tokens", 0), "cache_creation_1h_input_tokens"))
    unknown_raw = run.get("cache_creation_unknown_input_tokens")
    unknown = (
        max(0, created - five - one_hour)
        if unknown_raw is None
        else int(_number(unknown_raw, "cache_creation_unknown_input_tokens"))
    )
    if five + one_hour + unknown != created:
        raise ValueError("cache creation TTL buckets must sum to cache_creation_input_tokens")
    fresh = int(_number(run.get("fresh_input_tokens", 0), "fresh_input_tokens"))
    cache_read = int(_number(run.get("cache_read_input_tokens", 0), "cache_read_input_tokens"))
    output = int(_number(run.get("output_tokens", 0), "output_tokens"))
    return {
        "fresh_input_tokens": fresh,
        "cache_creation_5m_input_tokens": five,
        "cache_creation_1h_input_tokens": one_hour,
        "cache_creation_unknown_input_tokens": unknown,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
    }


def _session_metrics(run: dict) -> dict:
    """Validate independently derived transcript behavior metrics."""
    metrics = run.get("session_metrics")
    if not isinstance(metrics, dict):
        raise ValueError("every run requires session_metrics")
    result = {}
    for name in (
        "tool_calls",
        "bash_calls",
        "unique_bash_commands",
        "repeat_command_calls",
        "retry_attempts",
        "duplicate_read_calls",
    ):
        result[name] = int(_number(metrics.get(name), f"session_metrics.{name}"))
    if result["tool_calls"] != int(_number(run.get("tool_calls", 0), "tool_calls")):
        raise ValueError("session_metrics.tool_calls must match transcript tool_calls")
    return result


def _efficiency_metrics(run: dict) -> dict:
    """Validate treatment-event telemetry used only for activation evidence."""
    telemetry = run.get("session_efficiency_telemetry")
    if not isinstance(telemetry, dict):
        raise ValueError("every run requires session_efficiency_telemetry")
    result = {}
    for name in (
        "events",
        "continuity_restores",
        "dedup_interventions",
        "cross_turn_output_dedups",
        "unchanged_read_blocks",
        "waste_signals",
        "retry_loop_signals",
        "repeated_command_signals",
        "tool_cascade_signals",
        "estimated_tool_context_tokens_saved",
    ):
        result[name] = int(_number(telemetry.get(name), f"session_efficiency_telemetry.{name}"))
    return result


def _profile_gate(payload: dict) -> tuple[bool, list[str]]:
    """Verify that the two arms differ only by the frozen efficiency switches."""
    issues: list[str] = []
    runner = payload.get("runner")
    profiles = runner.get("condition_profiles") if isinstance(runner, dict) else None
    if not isinstance(profiles, dict) or set(profiles) != {"baseline", "enabled"}:
        return False, ["missing_session_efficiency_condition_profiles"]

    baseline = profiles["baseline"]
    enabled = profiles["enabled"]
    if not isinstance(baseline, dict) or not isinstance(enabled, dict):
        return False, ["invalid_session_efficiency_condition_profiles"]
    if not _profile_installed(baseline):
        issues.append("control_does_not_install_acco")
    if not _profile_installed(enabled):
        issues.append("treatment_does_not_install_acco")
    if str(baseline.get("label") or "") != "v1.6-session-baseline":
        issues.append("control_label_mismatch")
    if str(enabled.get("label") or "") != "v1.7-session-efficiency":
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
        ignored = set(_REQUIRED_CONTROL_ENV)
        control_other = {
            key: value for key, value in baseline_env.items() if key not in ignored
        }
        treatment_other = {
            key: value for key, value in enabled_env.items() if key not in ignored
        }
        if control_other != treatment_other:
            issues.append("non_efficiency_condition_env_diff")
    command = runner.get("command")
    if (
        not isinstance(command, list)
        or "acco.session_holdout_docker" not in command
    ):
        issues.append("session_holdout_runner_missing")
    if runner.get("session_holdout_protocol_version") != 1:
        issues.append("session_holdout_protocol_version_mismatch")
    if runner.get("forced_fresh_session_boundary") is not True:
        issues.append("fresh_session_boundary_not_forced")
    if runner.get("continuity_source") != "SessionStart:resume":
        issues.append("continuity_source_mismatch")
    if runner.get("phase1_mode") != "investigation-no-edit":
        issues.append("phase1_mode_mismatch")
    if runner.get("phase2_mode") != "fresh-session-implementation":
        issues.append("phase2_mode_mismatch")
    for field in ("phase1_turns", "phase2_turns"):
        value = runner.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            issues.append(f"invalid_runner_field:{field}")
    return not issues, issues


def _protocol_gate(payload: dict) -> tuple[bool, list[str]]:
    """Verify frozen task/design identity and the session-efficiency protocol."""
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
        "session_efficiency_isolated",
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
    profiles_ok, profile_issues = _profile_gate(payload)
    issues.extend(profile_issues)
    return bool(not issues and profiles_ok), issues


def validate_session_holdout_definition(
    payload: dict,
    *,
    require_frozen: bool = True,
) -> dict:
    """Validate session-arm isolation before any paid run starts."""
    if require_frozen:
        valid, issues = _protocol_gate(payload)
    else:
        valid, issues = _profile_gate(payload)
        protocol = payload.get("protocol")
        if (
            not isinstance(protocol, dict)
            or protocol.get("session_efficiency_isolated") is not True
        ):
            issues.append("protocol_not_true:session_efficiency_isolated")
            valid = False
    if not valid:
        raise ValueError(
            "invalid session-efficiency holdout definition: "
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
            "baseline": "v1.6-session-baseline",
            "treatment": "v1.7-session-efficiency",
        },
    }


def _condition_summary(runs: list[dict], pricing: EffectivenessPricing) -> dict:
    """Aggregate one condition across exact run and transcript metrics."""
    successes = sum(bool(run["success"]) for run in runs)
    costs = []
    total_input = 0
    tool_calls = 0
    retries = 0
    repeat_commands = 0
    duplicate_reads = 0
    for run in runs:
        usage = _usage(run)
        session = _session_metrics(run)
        total_input += int(_number(run.get("input_tokens", 0), "input_tokens"))
        tool_calls += session["tool_calls"]
        retries += session["retry_attempts"]
        repeat_commands += session["repeat_command_calls"]
        duplicate_reads += session["duplicate_read_calls"]
        cost = pricing.cost(usage)
        costs.append(cost)
    cost_complete = all(value is not None for value in costs)
    total_cost = (
        sum(float(value) for value in costs if value is not None)
        if cost_complete
        else None
    )
    return {
        "runs": len(runs),
        "successes": successes,
        "success_rate": successes / len(runs),
        "tool_calls": tool_calls,
        "input_tokens": total_input,
        "retry_attempts": retries,
        "repeat_command_calls": repeat_commands,
        "duplicate_read_calls": duplicate_reads,
        "total_cost_usd": total_cost,
        "cost_complete": cost_complete,
        "cost_per_success_usd": (
            total_cost / successes
            if total_cost is not None and successes
            else None
        ),
    }


def _reduction(before: float | int | None, after: float | int | None) -> float | None:
    """Return fractional reduction when the baseline denominator is positive."""
    if before is None or after is None or before <= 0:
        return None
    return 1.0 - float(after) / float(before)


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _bootstrap(
    pairs: list[tuple[dict, dict]],
    pricing: EffectivenessPricing,
) -> dict:
    """Return task-cluster bootstrap intervals for the requested session metrics."""
    clusters: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for baseline, enabled in pairs:
        clusters[str(baseline["task"])].append((baseline, enabled))
    metrics = (
        "tool_calls",
        "input_tokens",
        "retry_attempts",
        "cost_per_success_usd",
    )
    if len(clusters) < 2:
        return {
            "samples": _BOOTSTRAP_SAMPLES,
            "seed": _BOOTSTRAP_SEED,
            "task_clusters": len(clusters),
            "intervals": dict.fromkeys(metrics),
        }

    rng = random.Random(_BOOTSTRAP_SEED)
    values: dict[str, list[float]] = {name: [] for name in metrics}
    cluster_values = list(clusters.values())
    for _index in range(_BOOTSTRAP_SAMPLES):
        selected = [
            cluster_values[rng.randrange(len(cluster_values))]
            for _cluster in cluster_values
        ]
        flattened = [pair for cluster in selected for pair in cluster]
        before = _condition_summary([pair[0] for pair in flattened], pricing)
        after = _condition_summary([pair[1] for pair in flattened], pricing)
        for name in metrics:
            reduction = _reduction(before[name], after[name])
            if reduction is not None:
                values[name].append(reduction)

    intervals = {}
    for name, samples in values.items():
        intervals[name] = (
            [_percentile(samples, 0.025), _percentile(samples, 0.975)]
            if len(samples) >= 0.9 * _BOOTSTRAP_SAMPLES
            else None
        )
    return {
        "samples": _BOOTSTRAP_SAMPLES,
        "seed": _BOOTSTRAP_SEED,
        "task_clusters": len(clusters),
        "intervals": intervals,
    }


def _activation(enabled_runs: list[dict]) -> dict:
    """Summarize treatment activations without treating them as outcome evidence."""
    totals = defaultdict(int)
    active_pairs = defaultdict(int)
    for run in enabled_runs:
        metrics = _efficiency_metrics(run)
        for key, value in metrics.items():
            totals[key] += value
        if metrics["dedup_interventions"] > 0:
            active_pairs["dedup"] += 1
        if metrics["continuity_restores"] > 0:
            active_pairs["continuity"] += 1
        if metrics["waste_signals"] > 0:
            active_pairs["waste"] += 1
    return {
        "totals": dict(sorted(totals.items())),
        "active_runs": {
            "dedup": active_pairs["dedup"],
            "continuity": active_pairs["continuity"],
            "waste": active_pairs["waste"],
        },
        "all_feature_families_observed": all(
            active_pairs[name] > 0 for name in ("dedup", "continuity", "waste")
        ),
        "causal_scope": (
            "Two-arm design estimates the combined session-efficiency bundle. "
            "Activation counts show which mechanisms fired but do not identify "
            "each feature's separate causal contribution."
        ),
    }


def evaluate_session_holdout(
    path: Path,
    *,
    pricing: EffectivenessPricing,
) -> dict:
    """Evaluate a frozen v1.6-behavior vs v1.7-session-efficiency holdout."""
    pricing.validate()
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("session holdout requires a non-empty runs list")

    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    trials_by_task: dict[str, set[int]] = defaultdict(set)
    manual_intervention = False
    identity_issues: list[str] = []
    for raw in runs:
        if not isinstance(raw, dict):
            raise ValueError("every session holdout run must be an object")
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
        _efficiency_metrics(raw)
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
        raise ValueError("unpaired session holdout trials: " + ", ".join(incomplete))

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
    activation = _activation(enabled_runs)
    baseline_activation = _activation(baseline_runs)
    bootstrap = _bootstrap(pairs, pricing)

    reductions = {
        "tool_calls": _reduction(baseline["tool_calls"], enabled["tool_calls"]),
        "input_tokens": _reduction(baseline["input_tokens"], enabled["input_tokens"]),
        "retry_attempts": _reduction(
            baseline["retry_attempts"], enabled["retry_attempts"]
        ),
        "repeat_command_calls": _reduction(
            baseline["repeat_command_calls"], enabled["repeat_command_calls"]
        ),
        "duplicate_read_calls": _reduction(
            baseline["duplicate_read_calls"], enabled["duplicate_read_calls"]
        ),
        "cost_per_success": _reduction(
            baseline["cost_per_success_usd"], enabled["cost_per_success_usd"]
        ),
    }

    trial_counts = [len(values) for values in trials_by_task.values()]
    blockers: list[str] = []
    if len(trials_by_task) < MIN_PUBLISHABLE_TASKS:
        blockers.append("insufficient_distinct_tasks")
    if min(trial_counts) < MIN_PUBLISHABLE_TRIALS_PER_TASK:
        blockers.append("insufficient_trials_per_task")
    if not protocol_valid:
        blockers.append("invalid_or_unfrozen_session_protocol")
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
    if any(value for value in baseline_activation["totals"].values()):
        blockers.append("control_session_efficiency_not_disabled")
    if (
        activation["totals"].get("continuity_restores", 0)
        < len(enabled_runs)
    ):
        blockers.append("forced_continuity_restore_missing")
    if not activation["all_feature_families_observed"]:
        blockers.append("session_feature_coverage_incomplete")
    cost_reduction = reductions["cost_per_success"]
    if cost_reduction is None or cost_reduction <= 0:
        blockers.append("no_positive_cost_per_success_reduction")
    interval = bootstrap["intervals"]["cost_per_success_usd"]
    if interval is None or interval[0] <= 0:
        blockers.append("cost_per_success_ci_not_strictly_positive")

    return {
        "schema": 1,
        "comparison": {
            "baseline": "v1.6-session-baseline",
            "treatment": "v1.7-session-efficiency",
            "causal_scope": "combined_bundle_only",
        },
        "tasks": len(trials_by_task),
        "paired_trials": len(pairs),
        "trials_per_task": {
            "min": min(trial_counts),
            "max": max(trial_counts),
        },
        "conditions": {
            "baseline": baseline,
            "session-efficiency": enabled,
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

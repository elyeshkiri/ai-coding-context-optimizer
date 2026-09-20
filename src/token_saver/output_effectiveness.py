"""Join measured runtime usage with independent success and blind quality evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import random
import statistics
from pathlib import Path

from .agent_eval import QUALITY_WEIGHTS
from .benchmark import MIN_PUBLISHABLE_TASKS, MIN_PUBLISHABLE_TRIALS_PER_TASK
from .paired_conditions import (
    BASELINE_CONDITION,
    OPTIMIZED_CONDITION,
    normalize_condition,
)

EFFECTIVENESS_SCHEMA = 1
_BOOTSTRAP_SAMPLES = 2000
_BOOTSTRAP_SEED = 20260920
_PARITY_TOLERANCE = 0.10


@dataclass(frozen=True)
class EffectivenessPricing:
    """Price exact transcript usage categories in USD per million tokens."""

    fresh_input_per_million: float = 0.0
    cache_creation_per_million: float = 0.0
    cache_read_per_million: float = 0.0
    output_per_million: float = 0.0

    def supplied(self) -> bool:
        """Return whether any nonzero pricing rate was supplied."""
        return any(
            value > 0
            for value in (
                self.fresh_input_per_million,
                self.cache_creation_per_million,
                self.cache_read_per_million,
                self.output_per_million,
            )
        )

    def cost(self, usage: dict) -> float:
        """Return USD cost for one exact usage breakdown."""
        return (
            usage["fresh_input_tokens"] * self.fresh_input_per_million
            + usage["cache_creation_input_tokens"]
            * self.cache_creation_per_million
            + usage["cache_read_input_tokens"] * self.cache_read_per_million
            + usage["output_tokens"] * self.output_per_million
        ) / 1_000_000


def _number(value: object, field: str, *, integer: bool = True) -> int | float:
    """Validate a finite nonnegative numeric manifest field."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a nonnegative number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field} must be a nonnegative number")
    if integer:
        if int(numeric) != numeric:
            raise ValueError(f"{field} must be an integer")
        return int(numeric)
    return numeric


def _trial(value: object, task: str, condition: str) -> int:
    """Normalize one positive paired-run trial number."""
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"trial must be a positive integer: {task}/{condition}")
    return value


def _usage(run: dict) -> dict:
    """Extract exact usage where available, with a legacy total-input fallback."""
    output = int(_number(run.get("output_tokens", 0), "output_tokens"))
    cache_created = int(
        _number(run.get("cache_creation_input_tokens", 0), "cache_creation_input_tokens")
    )
    cache_read = int(
        _number(
            run.get("cache_read_input_tokens", run.get("cached_input_tokens", 0)),
            "cache_read_input_tokens",
        )
    )
    if "fresh_input_tokens" in run:
        fresh = int(_number(run["fresh_input_tokens"], "fresh_input_tokens"))
    else:
        total = int(_number(run.get("input_tokens", 0), "input_tokens"))
        fresh = max(0, total - cache_created - cache_read)
    return {
        "fresh_input_tokens": fresh,
        "cache_creation_input_tokens": cache_created,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
        "model_calls": int(_number(run.get("model_calls", 0), "model_calls")),
    }


def _weighted_quality(quality: dict) -> float:
    """Return the shared weighted blind-response quality score."""
    total = 0.0
    for name, weight in QUALITY_WEIGHTS.items():
        value = quality.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"quality.{name} must be numeric")
        score = float(value)
        if score < 1 or score > 5:
            raise ValueError(f"quality.{name} must be between 1 and 5")
        total += score * weight
    return total


def _quality(run: dict) -> tuple[dict | None, bool]:
    """Validate optional quality and blocker evidence for one run."""
    has_quality = "quality" in run or "blocker" in run
    if not has_quality:
        return None, False
    quality = run.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("quality must be an object when supplied")
    weighted = _weighted_quality(quality)
    blocker = run.get("blocker", False)
    if not isinstance(blocker, bool):
        raise ValueError("blocker must be boolean")
    normalized = {
        name: float(quality[name])
        for name in QUALITY_WEIGHTS
    }
    normalized["weighted_score"] = weighted
    return normalized, blocker


def _pair_quality_safe(baseline: dict, optimized: dict) -> bool | None:
    """Return pair-level quality preservation, or None when grades are absent."""
    base_quality, base_blocker = _quality(baseline)
    opt_quality, opt_blocker = _quality(optimized)
    if base_quality is None and opt_quality is None:
        return None
    if base_quality is None or opt_quality is None:
        raise ValueError("quality evidence must be present for both runs in a pair")
    if not baseline["success"] or not optimized["success"]:
        return False
    return (
        opt_quality["correctness"]
        >= base_quality["correctness"] - _PARITY_TOLERANCE
        and opt_quality["safety"]
        >= base_quality["safety"] - _PARITY_TOLERANCE
        and opt_quality["weighted_score"]
        >= base_quality["weighted_score"] - _PARITY_TOLERANCE
        and int(opt_blocker) <= int(base_blocker)
    )


def _quality_summary(runs: list[dict]) -> dict | None:
    """Aggregate complete quality evidence for one condition."""
    evidence = [_quality(run) for run in runs]
    if all(quality is None for quality, _blocker in evidence):
        return None
    if any(quality is None for quality, _blocker in evidence):
        raise ValueError("quality evidence must cover every paired run or be omitted")
    dimensions = {
        name: statistics.fmean(
            quality[name] for quality, _blocker in evidence if quality is not None
        )
        for name in QUALITY_WEIGHTS
    }
    weighted = statistics.fmean(
        quality["weighted_score"]
        for quality, _blocker in evidence
        if quality is not None
    )
    blockers = sum(int(blocker) for _quality_value, blocker in evidence)
    return {
        "dimensions": dimensions,
        "weighted_score": weighted,
        "blockers": blockers,
    }


def _cost(run: dict, usage: dict, pricing: EffectivenessPricing) -> float | None:
    """Return measured or rate-derived cost for one run."""
    if "cost_usd" in run:
        return float(_number(run["cost_usd"], "cost_usd", integer=False))
    if not pricing.supplied():
        return None
    return pricing.cost(usage)


def _condition_summary(runs: list[dict], pricing: EffectivenessPricing) -> dict:
    """Aggregate success, exact usage, and optional cost for one condition."""
    usages = [_usage(run) for run in runs]
    costs = [_cost(run, usage, pricing) for run, usage in zip(runs, usages)]
    successes = sum(bool(run["success"]) for run in runs)
    complete_cost = all(cost is not None for cost in costs)
    total_cost = sum(float(cost) for cost in costs if cost is not None)
    return {
        "runs": len(runs),
        "successes": successes,
        "success_rate": successes / len(runs),
        "fresh_input_tokens": sum(item["fresh_input_tokens"] for item in usages),
        "cache_creation_input_tokens": sum(
            item["cache_creation_input_tokens"] for item in usages
        ),
        "cache_read_input_tokens": sum(item["cache_read_input_tokens"] for item in usages),
        "output_tokens": sum(item["output_tokens"] for item in usages),
        "model_calls": sum(item["model_calls"] for item in usages),
        "cost_complete": complete_cost,
        "total_cost_usd": total_cost if complete_cost else None,
        "cost_per_success_usd": (
            total_cost / successes if complete_cost and successes else None
        ),
    }


def _safe_reduction(before: float | None, after: float | None) -> float | None:
    """Return fractional reduction only when both values are usable."""
    if before is None or after is None or before <= 0:
        return None
    return 1.0 - after / before


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile."""
    if not values:
        return None
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


def _budget_group(records: list[dict], pricing: EffectivenessPricing) -> dict:
    """Summarize one optimized output task/mode/budget cohort."""
    outputs = [_usage(record["run"])["output_tokens"] for record in records]
    utilizations = [
        float(record["telemetry"]["mean_budget_utilization"])
        for record in records
        if isinstance(record["telemetry"].get("mean_budget_utilization"), (int, float))
        and not isinstance(record["telemetry"].get("mean_budget_utilization"), bool)
    ]
    safe = [record["pair_quality_safe"] for record in records]
    known_safe = [value for value in safe if value is not None]
    successes = sum(bool(record["run"]["success"]) for record in records)
    costs = [
        _cost(record["run"], _usage(record["run"]), pricing)
        for record in records
    ]
    complete_cost = all(cost is not None for cost in costs)
    total_cost = sum(float(cost) for cost in costs if cost is not None)
    task_count = len({str(record["run"]["task"]) for record in records})
    budget = records[0]["telemetry"].get("policy_budget")
    p90_output = _percentile([float(value) for value in outputs], 0.90)
    candidate = bool(
        isinstance(budget, int)
        and budget > 0
        and len(records) >= 3
        and task_count >= 3
        and successes == len(records)
        and known_safe
        and len(known_safe) == len(records)
        and all(known_safe)
        and p90_output is not None
        and p90_output < budget
    )
    return {
        "runs": len(records),
        "tasks": task_count,
        "successes": successes,
        "success_rate": successes / len(records),
        "quality_safe_runs": sum(value is True for value in known_safe),
        "quality_safe_rate": (
            sum(value is True for value in known_safe) / len(known_safe)
            if known_safe
            else None
        ),
        "mean_output_tokens": statistics.fmean(outputs) if outputs else None,
        "p90_output_tokens": p90_output,
        "mean_budget_utilization": (
            statistics.fmean(utilizations) if utilizations else None
        ),
        "cost_complete": complete_cost,
        "total_cost_usd": total_cost if complete_cost else None,
        "cost_per_success_usd": (
            total_cost / successes if complete_cost and successes else None
        ),
        "eligible_for_calibration": candidate,
    }

def _bootstrap(
    pairs: list[tuple[dict, dict]],
    pricing: EffectivenessPricing,
) -> dict:
    """Bootstrap cost/success change over whole task clusters."""
    clusters: dict[str, list[tuple[dict, dict]]] = {}
    for baseline, optimized in pairs:
        clusters.setdefault(str(baseline["task"]), []).append((baseline, optimized))
    if len(clusters) < 2:
        return {
            "samples": _BOOTSTRAP_SAMPLES,
            "seed": _BOOTSTRAP_SEED,
            "task_clusters": len(clusters),
            "cost_per_success_reduction_ci95": None,
            "note": "at least 2 distinct tasks are required for an interval",
        }

    rng = random.Random(_BOOTSTRAP_SEED)
    cluster_values = list(clusters.values())
    samples: list[float] = []
    for _ in range(_BOOTSTRAP_SAMPLES):
        selected = [
            cluster_values[rng.randrange(len(cluster_values))]
            for _index in cluster_values
        ]
        flattened = [pair for cluster in selected for pair in cluster]
        base_runs = [pair[0] for pair in flattened]
        opt_runs = [pair[1] for pair in flattened]
        base = _condition_summary(base_runs, pricing)
        opt = _condition_summary(opt_runs, pricing)
        reduction = _safe_reduction(
            base["cost_per_success_usd"],
            opt["cost_per_success_usd"],
        )
        if reduction is not None:
            samples.append(reduction)

    interval = None
    if len(samples) >= 0.9 * _BOOTSTRAP_SAMPLES:
        interval = [
            float(_percentile(samples, 0.025)),
            float(_percentile(samples, 0.975)),
        ]
    return {
        "samples": _BOOTSTRAP_SAMPLES,
        "seed": _BOOTSTRAP_SEED,
        "task_clusters": len(clusters),
        "cost_per_success_reduction_ci95": interval,
    }


def evaluate_output_effectiveness(
    path: Path,
    *,
    pricing: EffectivenessPricing | None = None,
) -> dict:
    """Join usage, policy telemetry, success, and blind quality for paired runs."""
    pricing = pricing or EffectivenessPricing()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("effectiveness manifest requires a non-empty 'runs' list")

    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    trials_by_task: dict[str, set[int]] = {}
    manual_intervention = False
    for position, raw in enumerate(raw_runs, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"run {position} must be an object")
        task = str(raw.get("task") or "").strip()
        condition = normalize_condition(raw.get("condition"))
        if not task or condition not in {BASELINE_CONDITION, OPTIMIZED_CONDITION}:
            raise ValueError(
                "each run requires task and condition baseline|token-saver|enabled"
            )
        trial = _trial(raw.get("trial"), task, condition)
        if not isinstance(raw.get("success"), bool):
            raise ValueError(f"success must be boolean: {task}/{trial}/{condition}")
        pair = grouped.setdefault((task, trial), {})
        if condition in pair:
            raise ValueError(f"duplicate {condition} run for task/trial: {task}/{trial}")
        run = dict(raw)
        run["task"] = task
        run["trial"] = trial
        run["condition"] = condition
        _usage(run)
        _quality(run)
        pair[condition] = run
        trials_by_task.setdefault(task, set()).add(trial)
        manual_intervention = manual_intervention or bool(
            run.get("manual_intervention", False)
        )

    incomplete = [
        f"{task}/{trial}"
        for (task, trial), pair in sorted(grouped.items())
        if set(pair) != {BASELINE_CONDITION, OPTIMIZED_CONDITION}
    ]
    if incomplete:
        raise ValueError("unpaired task/trials: " + ", ".join(incomplete))

    pairs = [
        (pair[BASELINE_CONDITION], pair[OPTIMIZED_CONDITION])
        for pair in grouped.values()
    ]
    pair_identity_mismatches = []
    pair_identity_missing = []
    for baseline_run, optimized_run in pairs:
        label = f"{baseline_run['task']}/{baseline_run['trial']}"
        for field in ("model", "prompt_sha256", "revision"):
            base_value = baseline_run.get(field)
            opt_value = optimized_run.get(field)
            if not base_value or not opt_value:
                pair_identity_missing.append(f"{label}:{field}")
            elif base_value != opt_value:
                pair_identity_mismatches.append(f"{label}:{field}")
    baseline_runs = [baseline for baseline, _optimized in pairs]
    optimized_runs = [optimized for _baseline, optimized in pairs]
    baseline = _condition_summary(baseline_runs, pricing)
    optimized = _condition_summary(optimized_runs, pricing)

    quality_meta = payload.get("quality_evaluation")
    blinded = bool(
        isinstance(quality_meta, dict)
        and quality_meta.get("blinded") is True
    )
    quality_judge = (
        str(quality_meta.get("judge") or "").strip()
        if isinstance(quality_meta, dict)
        else ""
    )
    protocol = payload.get("protocol")
    protocol_required_true = (
        "task_definitions_frozen",
        "condition_order_randomized",
        "independent_verification",
        "history_isolated",
        "hidden_tests_after_agent",
    )
    protocol_valid = bool(
        isinstance(protocol, dict)
        and all(protocol.get(name) is True for name in protocol_required_true)
        and isinstance(protocol.get("frozen_at"), str)
        and bool(protocol.get("frozen_at").strip())
        and isinstance(protocol.get("task_definition_sha256"), str)
        and len(protocol.get("task_definition_sha256").strip()) == 64
    )
    base_quality = _quality_summary(baseline_runs)
    opt_quality = _quality_summary(optimized_runs)
    quality_complete = base_quality is not None and opt_quality is not None
    quality_parity = False
    if quality_complete:
        quality_parity = (
            opt_quality["dimensions"]["correctness"]
            >= base_quality["dimensions"]["correctness"] - _PARITY_TOLERANCE
            and opt_quality["dimensions"]["safety"]
            >= base_quality["dimensions"]["safety"] - _PARITY_TOLERANCE
            and opt_quality["weighted_score"]
            >= base_quality["weighted_score"] - _PARITY_TOLERANCE
            and opt_quality["blockers"] <= base_quality["blockers"]
        )

    optimized_evidence: list[dict] = []
    incomplete_policy = []
    usage_mismatches = []
    for baseline_run, optimized_run in pairs:
        telemetry = optimized_run.get("output_policy_telemetry")
        key = f"{optimized_run['task']}/{optimized_run['trial']}"
        if not isinstance(telemetry, dict):
            incomplete_policy.append(key)
            continue
        if telemetry.get("usage_matches_transcript") is not True:
            usage_mismatches.append(key)
        optimized_evidence.append(
            {
                "run": optimized_run,
                "telemetry": telemetry,
                "pair_quality_safe": _pair_quality_safe(
                    baseline_run, optimized_run
                ),
            }
        )

    budget_groups: dict[str, list[dict]] = {}
    ungrouped = 0
    for record in optimized_evidence:
        telemetry = record["telemetry"]
        task = telemetry.get("output_task")
        mode = telemetry.get("output_mode")
        budget = telemetry.get("policy_budget")
        if (
            not isinstance(task, str)
            or not isinstance(mode, str)
            or isinstance(budget, bool)
            or not isinstance(budget, int)
            or budget <= 0
        ):
            ungrouped += 1
            continue
        budget_groups.setdefault(f"{task}:{mode}:{budget}", []).append(record)

    group_report = {
        key: _budget_group(records, pricing)
        for key, records in sorted(budget_groups.items())
    }

    success_parity = optimized["success_rate"] >= baseline["success_rate"]
    exact_usage_missing = []
    for run in baseline_runs + optimized_runs:
        if not all(
            field in run
            for field in (
                "fresh_input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "output_tokens",
                "model_calls",
            )
        ):
            exact_usage_missing.append(f"{run['task']}/{run['trial']}/{run['condition']}")
    cost_per_success_reduction = _safe_reduction(
        baseline["cost_per_success_usd"],
        optimized["cost_per_success_usd"],
    )
    trial_counts = [len(values) for values in trials_by_task.values()]
    bootstrap = _bootstrap(pairs, pricing)
    cost_ci = bootstrap["cost_per_success_reduction_ci95"]
    blockers = []
    if not protocol_valid:
        blockers.append("invalid_or_missing_frozen_experiment_protocol")
    if pair_identity_missing:
        blockers.append("incomplete_pair_identity")
    if pair_identity_mismatches:
        blockers.append("paired_run_identity_mismatch")
    if exact_usage_missing:
        blockers.append("incomplete_exact_transcript_usage")
    if len(trials_by_task) < MIN_PUBLISHABLE_TASKS:
        blockers.append("insufficient_distinct_tasks")
    if min(trial_counts) < MIN_PUBLISHABLE_TRIALS_PER_TASK:
        blockers.append("insufficient_trials_per_task")
    if manual_intervention:
        blockers.append("manual_intervention_present")
    if not success_parity:
        blockers.append("task_success_regression")
    if not blinded:
        blockers.append("missing_blind_quality_evidence")
    if not quality_judge:
        blockers.append("missing_quality_judge_identity")
    if not quality_complete:
        blockers.append("incomplete_quality_evidence")
    elif not quality_parity:
        blockers.append("quality_regression")
    if incomplete_policy:
        blockers.append("incomplete_output_policy_telemetry")
    if usage_mismatches:
        blockers.append("telemetry_transcript_usage_mismatch")
    if not baseline["cost_complete"] or not optimized["cost_complete"]:
        blockers.append("cost_evidence_incomplete")
    elif cost_per_success_reduction is None:
        blockers.append("cost_per_success_unavailable")
    elif cost_per_success_reduction <= 0:
        blockers.append("no_positive_cost_per_success_reduction")
    if cost_ci is None or cost_ci[0] <= 0:
        blockers.append("cost_per_success_ci_not_strictly_positive")

    return {
        "schema": EFFECTIVENESS_SCHEMA,
        "source": str(path),
        "tasks": len(trials_by_task),
        "paired_trials": len(pairs),
        "trials_per_task": {
            "min": min(trial_counts),
            "max": max(trial_counts),
        },
        "pricing": {
            "fresh_input_per_million": pricing.fresh_input_per_million,
            "cache_creation_per_million": pricing.cache_creation_per_million,
            "cache_read_per_million": pricing.cache_read_per_million,
            "output_per_million": pricing.output_per_million,
            "supplied": pricing.supplied(),
        },
        "conditions": {
            BASELINE_CONDITION: baseline,
            OPTIMIZED_CONDITION: optimized,
        },
        "delta": {
            "success_rate_change": (
                optimized["success_rate"] - baseline["success_rate"]
            ),
            "cost_per_success_reduction": cost_per_success_reduction,
            "output_token_reduction": _safe_reduction(
                float(baseline["output_tokens"]),
                float(optimized["output_tokens"]),
            ),
        },
        "protocol": {
            "valid": protocol_valid,
            "required_true": list(protocol_required_true),
            "pair_identity_missing": pair_identity_missing,
            "pair_identity_mismatches": pair_identity_mismatches,
            "exact_usage_missing": exact_usage_missing,
        },
        "quality": {
            "blinded": blinded,
            "judge": quality_judge or None,
            "baseline": base_quality,
            "token_saver": opt_quality,
            "parity": quality_parity,
            "tolerance": _PARITY_TOLERANCE,
        },
        "telemetry": {
            "optimized_runs": len(optimized_runs),
            "runs_with_policy_telemetry": len(optimized_evidence),
            "incomplete_runs": incomplete_policy,
            "usage_mismatches": usage_mismatches,
            "ungrouped_runs": ungrouped,
        },
        "budget_groups": group_report,
        "bootstrap": bootstrap,
        "publication_gate": {
            "required_tasks": MIN_PUBLISHABLE_TASKS,
            "required_trials_per_task": MIN_PUBLISHABLE_TRIALS_PER_TASK,
            "passed": not blockers,
            "blockers": blockers,
        },
        "claim_allowed": not blockers,
    }

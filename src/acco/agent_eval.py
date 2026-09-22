"""Evaluate paired baseline/Token Saver agent outcomes without inventing quality."""

from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path

from .paired_conditions import (
    BASELINE_CONDITION,
    OPTIMIZED_CONDITION,
    normalize_condition,
)

CONDITIONS = {BASELINE_CONDITION, OPTIMIZED_CONDITION}
QUALITY_WEIGHTS = {
    "correctness": 0.40,
    "completeness": 0.20,
    "actionability": 0.15,
    "safety": 0.15,
    "concision": 0.10,
}
_BOOTSTRAP_SEED = 1729
_BOOTSTRAP_SAMPLES = 2000


def _quality_summary(runs: list[dict]) -> dict | None:
    """Aggregate optional blind response-quality scores without inventing missing grades."""
    with_quality = ["quality" in run or "blocker" in run for run in runs]
    if not any(with_quality):
        return None
    if not all(with_quality):
        raise ValueError("quality evidence must be present for every paired run or omitted entirely")

    totals = dict.fromkeys(QUALITY_WEIGHTS, 0.0)
    blockers = 0
    for run in runs:
        quality = run.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("quality must be an object when quality evidence is supplied")
        for name in QUALITY_WEIGHTS:
            value = quality.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"quality.{name} must be a number from 1 to 5")
            score = float(value)
            if score < 1 or score > 5:
                raise ValueError(f"quality.{name} must be a number from 1 to 5")
            totals[name] += score
        blocker = run.get("blocker", False)
        if not isinstance(blocker, bool):
            raise ValueError("blocker must be boolean")
        blockers += int(blocker)

    count = len(runs)
    means = {name: total / count for name, total in totals.items()}
    weighted = sum(means[name] * weight for name, weight in QUALITY_WEIGHTS.items())
    return {
        "dimensions": means,
        "weighted_score": weighted,
        "blockers": blockers,
    }


def _trial_number(run: dict, task: str, condition: str) -> int:
    """Return a positive trial number, defaulting legacy one-pair manifests to trial 1."""
    value = run.get("trial", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"trial must be a positive integer: {task}/{condition}")
    return value


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile for a non-empty numeric sample."""
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


def _bootstrap_mean_ci(values: list[float]) -> list[float] | None:
    """Return a deterministic 95% bootstrap CI for the paired mean."""
    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(_BOOTSTRAP_SEED)
    means = []
    for _ in range(_BOOTSTRAP_SAMPLES):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.fmean(sample))
    low = _percentile(means, 0.025)
    high = _percentile(means, 0.975)
    assert low is not None and high is not None
    return [low, high]


def _distribution(values: list[float]) -> dict | None:
    """Summarize paired reductions without assuming they are normally distributed."""
    if not values:
        return None
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "mean_ci95": _bootstrap_mean_ci(values),
    }


def _pair_reduction(baseline: int, optimized: int) -> float | None:
    """Return fractional reduction for one pair when the baseline denominator exists."""
    if baseline <= 0:
        return None
    return 1.0 - optimized / baseline


def evaluate_agent_runs(path: Path) -> dict:
    """Evaluate paired runs across one or more trials per task."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("agent outcome manifest must contain a non-empty 'runs' list")

    grouped: dict[tuple[str, int], dict[str, dict]] = {}
    trials_by_task: dict[str, set[int]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("every run must be an object")
        task = str(run.get("task", "")).strip()
        raw_condition = run.get("condition", "")
        condition = normalize_condition(raw_condition)
        if not task or condition not in CONDITIONS:
            raise ValueError(
                "each run needs task and condition baseline|token-saver|enabled"
            )
        trial = _trial_number(run, task, condition)
        key = (task, trial)
        pair = grouped.setdefault(key, {})
        if condition in pair:
            raise ValueError(f"duplicate {condition} run for task/trial: {task}/{trial}")
        if not isinstance(run.get("success"), bool):
            raise ValueError(f"run success must be boolean: {task}/{trial}/{condition}")
        pair[condition] = run
        trials_by_task.setdefault(task, set()).add(trial)

    incomplete = sorted(
        f"{task}/{trial}"
        for (task, trial), pair in grouped.items()
        if set(pair) != CONDITIONS
    )
    if incomplete:
        raise ValueError("unpaired task/trials: " + ", ".join(incomplete))

    summaries = {}
    for condition in sorted(CONDITIONS):
        selected = [pair[condition] for pair in grouped.values()]
        successes = sum(bool(run["success"]) for run in selected)
        input_tokens = sum(int(run.get("input_tokens", 0)) for run in selected)
        output_tokens = sum(int(run.get("output_tokens", 0)) for run in selected)
        summaries[condition] = {
            "runs": len(selected),
            "successes": successes,
            "success_rate": successes / len(selected),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "output_tokens_per_success": (
                output_tokens / successes if successes else None
            ),
            "tokens_per_success": (
                (input_tokens + output_tokens) / successes if successes else None
            ),
            "seconds": sum(float(run.get("seconds", 0)) for run in selected),
            "retries": sum(int(run.get("retries", 0)) for run in selected),
            "context_failures": sum(
                bool(run.get("context_failure", False)) for run in selected
            ),
        }

    base = summaries["baseline"]
    enabled = summaries["token-saver"]
    task_success_parity = enabled["success_rate"] >= base["success_rate"]

    quality_evidence = None
    quality_parity = task_success_parity
    all_runs = [run for pair in grouped.values() for run in pair.values()]
    if any("quality" in run or "blocker" in run for run in all_runs):
        metadata = payload.get("quality_evaluation")
        if not isinstance(metadata, dict):
            raise ValueError("quality_evaluation metadata is required with quality scores")
        blinded = metadata.get("blinded")
        if not isinstance(blinded, bool):
            raise ValueError("quality_evaluation.blinded must be boolean")

        baseline_quality = _quality_summary(
            [pair["baseline"] for pair in grouped.values()]
        )
        enabled_quality = _quality_summary(
            [pair["token-saver"] for pair in grouped.values()]
        )
        assert baseline_quality is not None and enabled_quality is not None
        dimensions_ok = all(
            enabled_quality["dimensions"][name]
            >= baseline_quality["dimensions"][name] - 0.10
            for name in ("correctness", "safety")
        )
        blockers_ok = enabled_quality["blockers"] <= baseline_quality["blockers"]
        weighted_ok = (
            enabled_quality["weighted_score"]
            >= baseline_quality["weighted_score"] - 0.10
        )
        quality_parity = (
            task_success_parity and dimensions_ok and blockers_ok and weighted_ok
        )
        quality_evidence = {
            "blinded": blinded,
            "judge": metadata.get("judge"),
            "rubric": {
                "weights": QUALITY_WEIGHTS,
                "parity_tolerance": 0.10,
            },
            "baseline": baseline_quality,
            "token-saver": enabled_quality,
        }

    raw_output_reduction = (
        _pair_reduction(base["output_tokens"], enabled["output_tokens"])
        if base["output_tokens"] > 0
        else None
    )
    tokens_per_success_reduction = None
    output_tokens_per_success_reduction = None
    if task_success_parity:
        if (
            base["tokens_per_success"]
            and enabled["tokens_per_success"] is not None
        ):
            tokens_per_success_reduction = (
                1.0
                - enabled["tokens_per_success"] / base["tokens_per_success"]
            )
        if (
            base["output_tokens_per_success"]
            and enabled["output_tokens_per_success"] is not None
        ):
            output_tokens_per_success_reduction = (
                1.0
                - enabled["output_tokens_per_success"]
                / base["output_tokens_per_success"]
            )

    paired_output_reductions = []
    paired_total_reductions = []
    paired_success_output_reductions = []
    for pair in grouped.values():
        baseline = pair["baseline"]
        optimized = pair["token-saver"]
        base_output = int(baseline.get("output_tokens", 0))
        enabled_output = int(optimized.get("output_tokens", 0))
        output_reduction = _pair_reduction(base_output, enabled_output)
        if output_reduction is not None:
            paired_output_reductions.append(output_reduction)

        base_total = int(baseline.get("input_tokens", 0)) + base_output
        enabled_total = int(optimized.get("input_tokens", 0)) + enabled_output
        total_reduction = _pair_reduction(base_total, enabled_total)
        if total_reduction is not None:
            paired_total_reductions.append(total_reduction)

        if baseline["success"] and optimized["success"] and output_reduction is not None:
            paired_success_output_reductions.append(output_reduction)

    trial_counts = [len(values) for values in trials_by_task.values()]
    paired = {
        "paired_trial_count": len(grouped),
        "unique_task_count": len(trials_by_task),
        "trials_per_task": {
            "min": min(trial_counts),
            "max": max(trial_counts),
        },
        "output_token_reduction": _distribution(paired_output_reductions),
        "total_token_reduction": _distribution(paired_total_reductions),
        "successful_pair_output_token_reduction": _distribution(
            paired_success_output_reductions
        ),
        "bootstrap": {
            "samples": _BOOTSTRAP_SAMPLES,
            "seed": _BOOTSTRAP_SEED,
        },
    }

    blind_quality_verified = bool(
        quality_evidence is not None
        and quality_evidence["blinded"]
        and quality_parity
    )
    claim_blockers = []
    if not task_success_parity:
        claim_blockers.append("task_success_regression")
    if quality_evidence is None:
        claim_blockers.append("missing_blind_quality_evidence")
    elif not quality_evidence["blinded"]:
        claim_blockers.append("quality_evidence_not_blinded")
    elif not quality_parity:
        claim_blockers.append("quality_regression")
    if tokens_per_success_reduction is None:
        claim_blockers.append("tokens_per_success_unavailable")
    elif tokens_per_success_reduction <= 0:
        claim_blockers.append("no_positive_tokens_per_success_reduction")

    return {
        "tasks": len(trials_by_task),
        "paired_trials": len(grouped),
        "conditions": summaries,
        "task_success_parity": task_success_parity,
        "quality_parity": quality_parity,
        "quality_evidence": quality_evidence,
        "blind_quality_verified": blind_quality_verified,
        "raw_output_token_reduction": raw_output_reduction,
        "output_tokens_per_success_reduction": output_tokens_per_success_reduction,
        "tokens_per_success_reduction": tokens_per_success_reduction,
        "paired": paired,
        "claim_allowed": not claim_blockers,
        "claim_blockers": claim_blockers,
    }

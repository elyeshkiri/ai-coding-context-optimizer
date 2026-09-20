"""Evaluate paired baseline/Token Saver agent outcomes without inventing quality."""

from __future__ import annotations

import json
from pathlib import Path

CONDITIONS = {"baseline", "token-saver"}
QUALITY_WEIGHTS = {
    "correctness": 0.40,
    "completeness": 0.20,
    "actionability": 0.15,
    "safety": 0.15,
    "concision": 0.10,
}


def _quality_summary(runs: list[dict]) -> dict | None:
    """Aggregate optional blind response-quality scores without inventing missing grades."""
    with_quality = ["quality" in run or "blocker" in run for run in runs]
    if not any(with_quality):
        return None
    if not all(with_quality):
        raise ValueError("quality evidence must be present for every paired run or omitted entirely")

    totals = {name: 0.0 for name in QUALITY_WEIGHTS}
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


def evaluate_agent_runs(path: Path) -> dict:
    """Evaluate agent runs."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("agent outcome manifest must contain a non-empty 'runs' list")
    grouped: dict[str, dict[str, dict]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("every run must be an object")
        task = str(run.get("task", "")).strip()
        condition = str(run.get("condition", ""))
        if not task or condition not in CONDITIONS:
            raise ValueError("each run needs task and condition baseline|token-saver")
        if condition in grouped.setdefault(task, {}):
            raise ValueError(f"duplicate {condition} run for task: {task}")
        if not isinstance(run.get("success"), bool):
            raise ValueError(f"run success must be boolean: {task}/{condition}")
        grouped[task][condition] = run
    incomplete = sorted(task for task, pair in grouped.items() if set(pair) != CONDITIONS)
    if incomplete:
        raise ValueError("unpaired tasks: " + ", ".join(incomplete))

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
            "tokens_per_success": (
                (input_tokens + output_tokens) / successes if successes else None
            ),
            "seconds": sum(float(run.get("seconds", 0)) for run in selected),
            "retries": sum(int(run.get("retries", 0)) for run in selected),
            "context_failures": sum(bool(run.get("context_failure", False)) for run in selected),
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
        quality_parity = task_success_parity and dimensions_ok and blockers_ok and weighted_ok
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

    comparable = quality_parity
    reduction = None
    output_reduction = None
    if comparable and base["tokens_per_success"] and enabled["tokens_per_success"] is not None:
        reduction = 1.0 - enabled["tokens_per_success"] / base["tokens_per_success"]
    if comparable and base["output_tokens"] > 0:
        output_reduction = 1.0 - enabled["output_tokens"] / base["output_tokens"]

    quality_publishable = quality_evidence is None or quality_evidence["blinded"]
    return {
        "tasks": len(grouped),
        "conditions": summaries,
        "task_success_parity": task_success_parity,
        "quality_parity": quality_parity,
        "quality_evidence": quality_evidence,
        "output_token_reduction": output_reduction,
        "tokens_per_success_reduction": reduction,
        "claim_allowed": comparable and reduction is not None and quality_publishable,
    }


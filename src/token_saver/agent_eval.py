"""Evaluate paired baseline/Token Saver agent outcomes without inventing quality."""

from __future__ import annotations

import json
from pathlib import Path

CONDITIONS = {"baseline", "token-saver"}


def evaluate_agent_runs(path: Path) -> dict:
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
    comparable = enabled["success_rate"] >= base["success_rate"]
    reduction = None
    if comparable and base["tokens_per_success"] and enabled["tokens_per_success"] is not None:
        reduction = 1.0 - enabled["tokens_per_success"] / base["tokens_per_success"]
    return {
        "tasks": len(grouped), "conditions": summaries,
        "quality_parity": comparable,
        "tokens_per_success_reduction": reduction,
        "claim_allowed": comparable and reduction is not None,
    }


"""Cost-per-success accounting for baseline vs Token Saver agent runs."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Pricing:
    input_per_million: float = 0.0
    output_per_million: float = 0.0
    cached_input_per_million: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int, cached_input_tokens: int) -> float:
        uncached = max(0, input_tokens - cached_input_tokens)
        return (
            uncached * self.input_per_million
            + output_tokens * self.output_per_million
            + cached_input_tokens * self.cached_input_per_million
        ) / 1_000_000


@dataclass(frozen=True)
class Run:
    task_id: str
    success: bool
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    tool_calls: int
    model_calls: int
    latency_ms: float
    cost_usd: float


def _number(value: Any, field: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    if value < 0:
        raise ValueError(f"{field} must be nonnegative")
    if integer:
        if int(value) != value:
            raise ValueError(f"{field} must be an integer")
        return int(value)
    return float(value)


def _runs_payload(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        raw = payload["runs"]
    else:
        raise ValueError(f"{path}: expected a JSON list or an object with a 'runs' list")
    if not raw:
        raise ValueError(f"{path}: run list must not be empty")
    if not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"{path}: every run must be an object")
    return raw


def load_runs(path: Path, pricing: Pricing | None = None) -> list[Run]:
    pricing = pricing or Pricing()
    seen: set[str] = set()
    runs: list[Run] = []
    for position, item in enumerate(_runs_payload(path), start=1):
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            raise ValueError(f"{path}: run {position} requires task_id")
        if task_id in seen:
            raise ValueError(f"{path}: duplicate task_id {task_id!r}")
        seen.add(task_id)
        success = item.get("success")
        if not isinstance(success, bool):
            raise ValueError(f"{path}: run {task_id!r} success must be boolean")
        input_tokens = int(_number(item.get("input_tokens", 0), "input_tokens", integer=True))
        output_tokens = int(_number(item.get("output_tokens", 0), "output_tokens", integer=True))
        cached = int(_number(item.get("cached_input_tokens", 0), "cached_input_tokens", integer=True))
        if cached > input_tokens:
            raise ValueError(f"{path}: cached_input_tokens cannot exceed input_tokens for {task_id!r}")
        tool_calls = int(_number(item.get("tool_calls", 0), "tool_calls", integer=True))
        model_calls = int(_number(item.get("model_calls", 1), "model_calls", integer=True))
        latency = float(_number(item.get("latency_ms", 0), "latency_ms"))
        if "cost_usd" in item:
            cost = float(_number(item["cost_usd"], "cost_usd"))
        else:
            if (
                pricing.input_per_million == 0
                and pricing.output_per_million == 0
                and pricing.cached_input_per_million == 0
            ):
                raise ValueError(
                    f"{path}: run {task_id!r} has no cost_usd and no token pricing was supplied"
                )
            cost = pricing.cost(input_tokens, output_tokens, cached)
        runs.append(Run(
            task_id=task_id,
            success=success,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached,
            tool_calls=tool_calls,
            model_calls=model_calls,
            latency_ms=latency,
            cost_usd=cost,
        ))
    return runs


def _safe_reduction(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return 1.0 - after / before


def _summary(runs: list[Run]) -> dict:
    successes = sum(run.success for run in runs)
    total_cost = sum(run.cost_usd for run in runs)
    input_tokens = sum(run.input_tokens for run in runs)
    output_tokens = sum(run.output_tokens for run in runs)
    cached_tokens = sum(run.cached_input_tokens for run in runs)
    latencies = [run.latency_ms for run in runs]
    return {
        "run_count": len(runs),
        "successes": successes,
        "success_rate": successes / len(runs),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached_tokens,
        "tool_calls": sum(run.tool_calls for run in runs),
        "model_calls": sum(run.model_calls for run in runs),
        "total_cost_usd": total_cost,
        "cost_per_run_usd": total_cost / len(runs),
        "cost_per_success_usd": total_cost / successes if successes else None,
        "mean_latency_ms": sum(latencies) / len(latencies),
        "median_latency_ms": median(latencies),
    }


def compare_costs(
    baseline: list[Run],
    optimized: list[Run],
    *,
    require_same_tasks: bool = True,
) -> dict:
    baseline_by_id = {run.task_id: run for run in baseline}
    optimized_by_id = {run.task_id: run for run in optimized}
    baseline_ids = set(baseline_by_id)
    optimized_ids = set(optimized_by_id)
    common = sorted(baseline_ids & optimized_ids)
    missing_optimized = sorted(baseline_ids - optimized_ids)
    missing_baseline = sorted(optimized_ids - baseline_ids)
    if require_same_tasks and (missing_optimized or missing_baseline):
        raise ValueError(
            "baseline and optimized runs must contain the same task_ids; "
            f"missing optimized={missing_optimized}, missing baseline={missing_baseline}"
        )
    if not common:
        raise ValueError("baseline and optimized runs share no task_ids")

    b = _summary([baseline_by_id[task] for task in common])
    o = _summary([optimized_by_id[task] for task in common])
    both_success = sum(
        baseline_by_id[task].success and optimized_by_id[task].success
        for task in common
    )
    improved = sorted(
        task for task in common
        if not baseline_by_id[task].success and optimized_by_id[task].success
    )
    regressed = sorted(
        task for task in common
        if baseline_by_id[task].success and not optimized_by_id[task].success
    )
    return {
        "paired_task_count": len(common),
        "baseline": b,
        "optimized": o,
        "delta": {
            "input_token_reduction": _safe_reduction(b["input_tokens"], o["input_tokens"]),
            "output_token_reduction": _safe_reduction(b["output_tokens"], o["output_tokens"]),
            "total_token_reduction": _safe_reduction(b["total_tokens"], o["total_tokens"]),
            "cost_reduction": _safe_reduction(b["total_cost_usd"], o["total_cost_usd"]),
            "cost_per_success_reduction": (
                _safe_reduction(b["cost_per_success_usd"], o["cost_per_success_usd"])
                if b["cost_per_success_usd"] is not None and o["cost_per_success_usd"] is not None
                else None
            ),
            "latency_reduction": _safe_reduction(b["mean_latency_ms"], o["mean_latency_ms"]),
            "success_rate_change": o["success_rate"] - b["success_rate"],
            "tool_call_change": o["tool_calls"] - b["tool_calls"],
            "model_call_change": o["model_calls"] - b["model_calls"],
        },
        "outcomes": {
            "both_success": both_success,
            "improved_tasks": improved,
            "regressed_tasks": regressed,
        },
        "task_alignment": {
            "missing_optimized": missing_optimized,
            "missing_baseline": missing_baseline,
        },
    }


def compare_cost_files(
    baseline_path: Path,
    optimized_path: Path,
    *,
    pricing: Pricing | None = None,
    require_same_tasks: bool = True,
) -> dict:
    pricing = pricing or Pricing()
    return compare_costs(
        load_runs(baseline_path, pricing),
        load_runs(optimized_path, pricing),
        require_same_tasks=require_same_tasks,
    )

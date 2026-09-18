"""Cost-per-success accounting for baseline vs Token Saver agent runs."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import random
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
    # Distinguishes repeated attempts of the same task (variance runs). Runs are
    # paired across conditions on (task_id, trial); empty means "the only run".
    trial: str = ""


def _trial(value: Any, where: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{where}: trial must be a string or integer")
    return str(value).strip()


def _label(task_id: str, trial: str) -> str:
    return f"{task_id}#{trial}" if trial else task_id


def _duplicate_message(where: str, task_id: str, trial: str, extra: str = "") -> str:
    if trial:
        return f"{where}: duplicate {extra}task_id {task_id!r} trial {trial!r}"
    return (
        f"{where}: duplicate {extra}task_id {task_id!r}; give repeated attempts "
        "of one task a distinct 'trial' so they can be paired and their "
        "variance measured"
    )


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
    seen: set[tuple[str, str]] = set()
    runs: list[Run] = []
    for position, item in enumerate(_runs_payload(path), start=1):
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            raise ValueError(f"{path}: run {position} requires task_id")
        trial = _trial(item.get("trial"), f"{path}: run {task_id!r}")
        if (task_id, trial) in seen:
            raise ValueError(_duplicate_message(str(path), task_id, trial))
        seen.add((task_id, trial))
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
            trial=trial,
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


def _index_runs(runs: list[Run], side: str) -> dict[tuple[str, str], Run]:
    indexed: dict[tuple[str, str], Run] = {}
    for run in runs:
        key = (run.task_id, run.trial)
        if key in indexed:
            # Never let a repeated (task_id, trial) silently collapse to the
            # last run: it would misstate success rate and cost with no signal.
            raise ValueError(_duplicate_message(side, run.task_id, run.trial))
        indexed[key] = run
    return indexed


_BOOTSTRAP_RESAMPLES = 2000
_BOOTSTRAP_SEED = 0


def _cluster_totals(members: list[tuple[Run, Run]]) -> tuple[float, ...]:
    return (
        sum(b.input_tokens + b.output_tokens for b, _ in members),
        sum(o.input_tokens + o.output_tokens for _, o in members),
        sum(b.cost_usd for b, _ in members),
        sum(o.cost_usd for _, o in members),
        sum(b.success for b, _ in members),
        sum(o.success for _, o in members),
        len(members),
    )


def _bootstrap_metrics(t: tuple[float, ...]) -> dict[str, float | None]:
    b_tok, o_tok, b_cost, o_cost, b_ok, o_ok, n = t
    cps = None
    if b_ok > 0 and o_ok > 0 and b_cost > 0:
        cps = 1.0 - (o_cost / o_ok) / (b_cost / b_ok)
    return {
        "total_token_reduction": 1.0 - o_tok / b_tok if b_tok > 0 else None,
        "cost_reduction": 1.0 - o_cost / b_cost if b_cost > 0 else None,
        "success_rate_change": o_ok / n - b_ok / n,
        "cost_per_success_reduction": cps,
    }


def _confidence(pairs: list[tuple[Run, Run]]) -> dict:
    """95% percentile intervals from a cluster bootstrap over tasks.

    Resampling whole tasks (not individual runs) keeps repeated trials of one
    task from being treated as independent evidence. Deterministic (seeded).
    """
    clusters: dict[str, list[tuple[Run, Run]]] = {}
    for baseline, optimized in pairs:
        clusters.setdefault(baseline.task_id, []).append((baseline, optimized))
    totals = [_cluster_totals(members) for members in clusters.values()]
    names = (
        "total_token_reduction", "cost_reduction",
        "success_rate_change", "cost_per_success_reduction",
    )
    out: dict = {
        "method": (
            f"cluster bootstrap over tasks, {_BOOTSTRAP_RESAMPLES} resamples, "
            f"seed {_BOOTSTRAP_SEED}, 95% percentile interval"
        ),
        "task_clusters": len(totals),
        "intervals": {name: None for name in names},
    }
    if len(totals) < 2:
        out["note"] = "at least 2 distinct tasks are required for an interval"
        return out
    rng = random.Random(_BOOTSTRAP_SEED)
    samples: dict[str, list[float]] = {name: [] for name in names}
    width = len(totals[0])
    for _ in range(_BOOTSTRAP_RESAMPLES):
        picked = [totals[rng.randrange(len(totals))] for _ in totals]
        summed = tuple(sum(row[i] for row in picked) for i in range(width))
        for name, value in _bootstrap_metrics(summed).items():
            if value is not None:
                samples[name].append(value)
    for name, values in samples.items():
        # Require most resamples to be defined (e.g. cost-per-success needs a
        # success in both arms) before reporting an interval at all.
        if len(values) >= 0.9 * _BOOTSTRAP_RESAMPLES:
            values.sort()
            low = values[int(0.025 * (len(values) - 1))]
            high = values[math.ceil(0.975 * (len(values) - 1))]
            out["intervals"][name] = [low, high]
    return out


def compare_costs(
    baseline: list[Run],
    optimized: list[Run],
    *,
    require_same_tasks: bool = True,
) -> dict:
    baseline_by_id = _index_runs(baseline, "baseline")
    optimized_by_id = _index_runs(optimized, "optimized")
    baseline_ids = set(baseline_by_id)
    optimized_ids = set(optimized_by_id)
    common = sorted(baseline_ids & optimized_ids)
    missing_optimized = sorted(_label(*k) for k in baseline_ids - optimized_ids)
    missing_baseline = sorted(_label(*k) for k in optimized_ids - baseline_ids)
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
        _label(*task) for task in common
        if not baseline_by_id[task].success and optimized_by_id[task].success
    )
    regressed = sorted(
        _label(*task) for task in common
        if baseline_by_id[task].success and not optimized_by_id[task].success
    )
    return {
        "paired_task_count": len(common),
        "unique_task_count": len({task_id for task_id, _ in common}),
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
        "confidence": _confidence(
            [(baseline_by_id[task], optimized_by_id[task]) for task in common]
        ),
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



def load_paired_agent_runs(path: Path, pricing: Pricing | None = None) -> tuple[list[Run], list[Run]]:
    """Load the same paired manifest accepted by agent-evaluate."""
    pricing = pricing or Pricing()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: paired agent manifest requires a non-empty 'runs' list")

    by_condition: dict[str, list[Run]] = {"baseline": [], "token-saver": []}
    seen: set[tuple[str, str, str]] = set()
    tasks_by_condition: dict[str, set[tuple[str, str]]] = {
        "baseline": set(), "token-saver": set(),
    }

    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: run {position} must be an object")
        task_id = str(item.get("task", "")).strip()
        condition = str(item.get("condition", "")).strip()
        if not task_id or condition not in by_condition:
            raise ValueError(
                f"{path}: each paired run requires task and condition baseline|token-saver"
            )
        trial = _trial(item.get("trial"), f"{path}: run {task_id!r}/{condition}")
        key = (task_id, trial, condition)
        if key in seen:
            raise ValueError(_duplicate_message(str(path), task_id, trial, f"{condition} run for "))
        seen.add(key)
        tasks_by_condition[condition].add((task_id, trial))

        success = item.get("success")
        if not isinstance(success, bool):
            raise ValueError(f"{path}: run {task_id!r}/{condition} success must be boolean")
        input_tokens = int(_number(item.get("input_tokens", 0), "input_tokens", integer=True))
        output_tokens = int(_number(item.get("output_tokens", 0), "output_tokens", integer=True))
        cached = int(_number(item.get("cached_input_tokens", 0), "cached_input_tokens", integer=True))
        if cached > input_tokens:
            raise ValueError(
                f"{path}: cached_input_tokens cannot exceed input_tokens for "
                f"{task_id!r}/{condition}"
            )
        tool_calls = int(_number(item.get("tool_calls", 0), "tool_calls", integer=True))
        model_calls = int(_number(item.get("model_calls", 1), "model_calls", integer=True))
        if "latency_ms" in item:
            latency = float(_number(item["latency_ms"], "latency_ms"))
        else:
            latency = float(_number(item.get("seconds", 0), "seconds")) * 1000.0

        if "cost_usd" in item:
            cost = float(_number(item["cost_usd"], "cost_usd"))
        else:
            if (
                pricing.input_per_million == 0
                and pricing.output_per_million == 0
                and pricing.cached_input_per_million == 0
            ):
                raise ValueError(
                    f"{path}: run {task_id!r}/{condition} has no cost_usd "
                    "and no token pricing was supplied"
                )
            cost = pricing.cost(input_tokens, output_tokens, cached)

        by_condition[condition].append(Run(
            task_id=task_id,
            success=success,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached,
            tool_calls=tool_calls,
            model_calls=model_calls,
            latency_ms=latency,
            cost_usd=cost,
            trial=trial,
        ))

    baseline_tasks = tasks_by_condition["baseline"]
    optimized_tasks = tasks_by_condition["token-saver"]
    if baseline_tasks != optimized_tasks:
        missing_optimized = sorted(_label(*k) for k in baseline_tasks - optimized_tasks)
        missing_baseline = sorted(_label(*k) for k in optimized_tasks - baseline_tasks)
        raise ValueError(
            f"{path}: unpaired tasks; missing token-saver={missing_optimized}, "
            f"missing baseline={missing_baseline}"
        )
    return by_condition["baseline"], by_condition["token-saver"]


def compare_paired_agent_file(path: Path, *, pricing: Pricing | None = None) -> dict:
    baseline, optimized = load_paired_agent_runs(path, pricing)
    return compare_costs(baseline, optimized, require_same_tasks=True)

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

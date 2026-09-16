"""Paired recorded-task evaluation. Never treats output size as task savings."""
import json
import math
from pathlib import Path
from .sessions import analyze
from .pricing import cost, load_rates

def evaluate(manifest_path, rates_path):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    runs = manifest.get("runs", [])
    if not runs: raise ValueError("manifest requires nonempty runs")
    rates = load_rates(rates_path)
    seen = set()
    used_paths = set()
    pairs = {}
    results = {arm: {"runs": 0, "successes": 0, "usd": 0.0, "seconds": 0.0,
                      "input_tokens": 0, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0, "output_tokens": 0,
                      "tool_results": 0, "repeated_reads": 0} for arm in ("baseline", "enabled")}
    for run in runs:
        arm = run["condition"]
        if arm not in results: raise ValueError("condition must be baseline or enabled")
        if not isinstance(run.get("success"), bool): raise ValueError("success must be independently evaluated boolean")
        seconds = run.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be a nonnegative finite number")
        if not run.get("validation"): raise ValueError("validation must describe the independent task checks")
        key = (run["task"], run["trial"])
        if (key, arm) in seen: raise ValueError("duplicate task/trial/condition")
        seen.add((key, arm))
        metadata = (run["revision"], run["model"], run["prompt_sha256"])
        if key in pairs and pairs[key] != metadata: raise ValueError("paired runs must share revision, model and prompt")
        pairs[key] = metadata
        paths = [(path.parent / p).resolve() for p in run["transcripts"]]
        if not paths or any(not p.is_file() for p in paths): raise ValueError("missing transcript")
        if len(set(paths)) != len(paths): raise ValueError("duplicate transcript in a run")
        if used_paths.intersection(paths): raise ValueError("transcripts must be independent across runs")
        used_paths.update(paths)
        report = analyze(paths)
        if not report.turns: raise ValueError("transcripts contain no measured usage")
        if any(t.model != run["model"] for t in report.turns): raise ValueError("transcript model differs from run model")
        bill = cost(report, rates)
        if bill["usd"] is None: raise ValueError("incomplete cost: " + "; ".join(bill["incomplete_reasons"]))
        result = results[arm]
        result["runs"] += 1; result["successes"] += int(run["success"])
        result["usd"] += bill["usd"]; result["seconds"] += seconds
        result["tool_results"] += len(report.calls)
        result["repeated_reads"] += sum(n - 1 for _, n, _ in report.duplicate_reads())
        for field in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            result[field] += report.usage[field]
    if any((key, arm) not in seen for key in pairs for arm in results): raise ValueError("every task/trial needs both conditions")
    for result in results.values():
        result["success_rate"] = result["successes"] / result["runs"]
        result["usd_per_success"] = result["usd"] / result["successes"] if result["successes"] else None
    baseline, enabled = results["baseline"], results["enabled"]
    comparable = enabled["success_rate"] >= baseline["success_rate"] and baseline["usd_per_success"] and enabled["usd_per_success"] is not None
    savings = 100 * (1 - enabled["usd_per_success"] / baseline["usd_per_success"]) if comparable else None
    return {"paired_trials": len(pairs), "results": results, "cost_per_success_reduction_percent": savings,
            "note": "Descriptive results only. Includes failed-run costs; quality checks are supplied by the evaluator. No statistical significance claim."}

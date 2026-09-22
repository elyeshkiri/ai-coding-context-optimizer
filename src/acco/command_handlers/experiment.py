"""Paired-agent experiment and cost-report CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..benchmark import task_definition_hash
from ..cost_report import Pricing, compare_cost_files, compare_paired_agent_file
from ..evidence_pipeline import run_evidence_pipeline
from ..experiment import run_experiment, validate_suite
from ..knowledge_holdout import evaluate_knowledge_holdout
from ..knowledge_holdout_pipeline import run_knowledge_holdout
from ..session_holdout import evaluate_session_holdout
from ..session_holdout_pipeline import load_session_pricing, run_session_holdout


def experiment_main(argv: list[str]) -> int:
    """Run the experiment command."""
    parser = argparse.ArgumentParser(prog="acco experiment")
    parser.add_argument("suite")
    parser.add_argument("--out", default="benchmark-runs.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the randomized schedule without running an agent",
    )
    parser.add_argument(
        "--allow-development",
        action="store_true",
        help="allow an unfrozen or smaller-than-publishable suite",
    )
    parser.add_argument(
        "--allow-user-hook",
        action="store_true",
        help="allow an existing user-level acco hook (can double-instrument enabled runs)",
    )
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="run only this frozen task id; repeat to run multiple tasks",
    )
    parser.add_argument(
        "--print-task-definition-hash",
        action="store_true",
        help="print the hash to freeze into protocol.task_definition_sha256",
    )
    args = parser.parse_args(argv)
    suite_path = Path(args.suite)
    try:
        if args.print_task_definition_hash:
            suite = validate_suite(
                suite_path,
                require_frozen=False,
                require_broad=False,
            )
            print(task_definition_hash(suite))
            return 0
        result = run_experiment(
            suite_path,
            Path(args.out),
            dry_run=args.dry_run,
            allow_development=args.allow_development,
            allow_user_hook=args.allow_user_hook,
            only_tasks=set(args.tasks) if args.tasks else None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def evidence_run_main(argv: list[str]) -> int:
    """Run/resume the complete experiment -> grade -> evidence pipeline."""
    parser = argparse.ArgumentParser(prog="acco evidence-run")
    parser.add_argument("suite")
    parser.add_argument("--out", default="benchmark-runs.json")
    parser.add_argument("--rates")
    parser.add_argument("--report")
    parser.add_argument("--calibration")
    parser.add_argument("--allow-development", action="store_true")
    parser.add_argument("--allow-user-hook", action="store_true")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--force-grades", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_evidence_pipeline(
            Path(args.suite),
            Path(args.out),
            rates_path=Path(args.rates) if args.rates else None,
            report_path=Path(args.report) if args.report else None,
            calibration_path=Path(args.calibration) if args.calibration else None,
            allow_development=args.allow_development,
            allow_user_hook=args.allow_user_hook,
            only_tasks=set(args.tasks) if args.tasks else None,
            force_grades=args.force_grades,
            dry_run=args.dry_run,
            require_publishable=args.require_publishable,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1 if args.require_publishable and "not publishable" in str(exc) else 2
    print(json.dumps(result, indent=2))
    return 0


def session_holdout_main(argv: list[str]) -> int:
    """Run/resume the frozen v1.6-vs-v1.7 session-efficiency holdout."""
    parser = argparse.ArgumentParser(prog="acco session-holdout")
    parser.add_argument("suite")
    parser.add_argument("--out", default="session-holdout-runs.json")
    parser.add_argument("--rates")
    parser.add_argument("--report")
    parser.add_argument("--allow-development", action="store_true")
    parser.add_argument("--allow-user-hook", action="store_true")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--force-grades", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_session_holdout(
            Path(args.suite),
            Path(args.out),
            rates_path=Path(args.rates) if args.rates else None,
            report_path=Path(args.report) if args.report else None,
            allow_development=args.allow_development,
            allow_user_hook=args.allow_user_hook,
            only_tasks=set(args.tasks) if args.tasks else None,
            force_grades=args.force_grades,
            dry_run=args.dry_run,
            require_publishable=args.require_publishable,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1 if args.require_publishable and "not publishable" in str(exc) else 2
    print(json.dumps(result, indent=2))
    return 0


def session_holdout_evaluate_main(argv: list[str]) -> int:
    """Evaluate an already-run and blind-graded session holdout manifest."""
    parser = argparse.ArgumentParser(prog="acco session-holdout-evaluate")
    parser.add_argument("manifest")
    parser.add_argument("--rates", required=True)
    parser.add_argument("--model")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        runner = payload.get("runner") if isinstance(payload, dict) else None
        model = args.model or (
            str(runner.get("model") or "")
            if isinstance(runner, dict)
            else ""
        )
        if not model:
            raise ValueError("model is required in manifest runner or --model")
        pricing = load_session_pricing(Path(args.rates), model)
        report = evaluate_session_holdout(Path(args.manifest), pricing=pricing)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        baseline = report["conditions"]["baseline"]
        enabled = report["conditions"]["session-efficiency"]
        print(
            "tools: "
            f"{baseline['tool_calls']} -> {enabled['tool_calls']} "
            f"({report['reductions']['tool_calls']})"
        )
        print(
            "input tokens: "
            f"{baseline['input_tokens']} -> {enabled['input_tokens']} "
            f"({report['reductions']['input_tokens']})"
        )
        print(
            "retries: "
            f"{baseline['retry_attempts']} -> {enabled['retry_attempts']} "
            f"({report['reductions']['retry_attempts']})"
        )
        print(
            "cost/success: "
            f"{baseline['cost_per_success_usd']} -> "
            f"{enabled['cost_per_success_usd']} "
            f"({report['reductions']['cost_per_success']})"
        )
        print(
            "publication gate: "
            + ("passed" if report["publication_gate"]["passed"] else "blocked")
        )
    if args.require_publishable and not report["publication_gate"]["passed"]:
        return 1
    return 0


def knowledge_holdout_main(argv: list[str]) -> int:
    """Run/resume the frozen knowledge-read-avoidance holdout."""
    parser = argparse.ArgumentParser(prog="acco knowledge-holdout")
    parser.add_argument("suite")
    parser.add_argument("--out", default="knowledge-holdout-runs.json")
    parser.add_argument("--rates")
    parser.add_argument("--report")
    parser.add_argument("--allow-development", action="store_true")
    parser.add_argument("--allow-user-hook", action="store_true")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--force-grades", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_knowledge_holdout(
            Path(args.suite),
            Path(args.out),
            rates_path=Path(args.rates) if args.rates else None,
            report_path=Path(args.report) if args.report else None,
            allow_development=args.allow_development,
            allow_user_hook=args.allow_user_hook,
            only_tasks=set(args.tasks) if args.tasks else None,
            force_grades=args.force_grades,
            dry_run=args.dry_run,
            require_publishable=args.require_publishable,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1 if args.require_publishable and "not publishable" in str(exc) else 2
    print(json.dumps(result, indent=2))
    return 0


def knowledge_holdout_evaluate_main(argv: list[str]) -> int:
    """Evaluate an already-run and blind-graded knowledge holdout manifest."""
    parser = argparse.ArgumentParser(prog="acco knowledge-holdout-evaluate")
    parser.add_argument("manifest")
    parser.add_argument("--rates", required=True)
    parser.add_argument("--model")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-publishable", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        runner = payload.get("runner") if isinstance(payload, dict) else None
        model = args.model or (
            str(runner.get("model") or "")
            if isinstance(runner, dict)
            else ""
        )
        if not model:
            raise ValueError("model is required in manifest runner or --model")
        pricing = load_session_pricing(Path(args.rates), model)
        report = evaluate_knowledge_holdout(Path(args.manifest), pricing=pricing)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        baseline = report["conditions"]["baseline"]
        enabled = report["conditions"]["knowledge-efficiency"]
        print(
            "tools: "
            f"{baseline['tool_calls']} -> {enabled['tool_calls']} "
            f"({report['reductions']['tool_calls']})"
        )
        print(
            "input tokens: "
            f"{baseline['input_tokens']} -> {enabled['input_tokens']} "
            f"({report['reductions']['input_tokens']})"
        )
        print(
            "duplicate reads: "
            f"{baseline['duplicate_read_calls']} -> "
            f"{enabled['duplicate_read_calls']} "
            f"({report['reductions']['duplicate_read_calls']})"
        )
        print(
            "cost/success: "
            f"{baseline['cost_per_success_usd']} -> "
            f"{enabled['cost_per_success_usd']} "
            f"({report['reductions']['cost_per_success']})"
        )
        print(
            "publication gate: "
            + ("passed" if report["publication_gate"]["passed"] else "blocked")
        )
    if args.require_publishable and not report["publication_gate"]["passed"]:
        return 1
    return 0


def cost_report_main(argv: list[str]) -> int:
    """Run the cost report command."""
    parser = argparse.ArgumentParser(prog="acco cost-report")
    parser.add_argument("baseline")
    parser.add_argument("optimized", nargs="?")
    parser.add_argument("--input-per-million", type=float, default=0.0)
    parser.add_argument("--output-per-million", type=float, default=0.0)
    parser.add_argument("--cached-input-per-million", type=float, default=0.0)
    parser.add_argument(
        "--allow-unpaired",
        action="store_true",
        help="compare only task_ids present in both files",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        pricing = Pricing(
            input_per_million=args.input_per_million,
            output_per_million=args.output_per_million,
            cached_input_per_million=args.cached_input_per_million,
        )
        if min(
            pricing.input_per_million,
            pricing.output_per_million,
            pricing.cached_input_per_million,
        ) < 0:
            raise ValueError("pricing values must be nonnegative")
        if args.optimized is None:
            if args.allow_unpaired:
                raise ValueError("--allow-unpaired is only valid in two-file mode")
            result = compare_paired_agent_file(
                Path(args.baseline),
                pricing=pricing,
            )
        else:
            result = compare_cost_files(
                Path(args.baseline),
                Path(args.optimized),
                pricing=pricing,
                require_same_tasks=not args.allow_unpaired,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    baseline, optimized, delta = (
        result["baseline"],
        result["optimized"],
        result["delta"],
    )

    def pct(value):
        """Render an optional ratio as a percentage."""
        return "n/a" if value is None else f"{value * 100:.1f}%"

    unique = result.get("unique_task_count", result["paired_task_count"])
    if unique != result["paired_task_count"]:
        print(f"PAIRED RUNS: {result['paired_task_count']} across {unique} tasks")
    else:
        print(f"PAIRED TASKS: {result['paired_task_count']}")
    print(
        f"success: {baseline['success_rate'] * 100:.1f}% -> "
        f"{optimized['success_rate'] * 100:.1f}% "
        f"({delta['success_rate_change'] * 100:+.1f} pp)"
    )
    print(
        f"tokens: {baseline['total_tokens']:,} -> {optimized['total_tokens']:,} "
        f"({pct(delta['total_token_reduction'])} reduction)"
    )
    print(
        f"cost: ${baseline['total_cost_usd']:.4f} -> "
        f"${optimized['total_cost_usd']:.4f} "
        f"({pct(delta['cost_reduction'])} reduction)"
    )
    before_cps = baseline["cost_per_success_usd"]
    after_cps = optimized["cost_per_success_usd"]
    if before_cps is not None and after_cps is not None:
        print(
            f"cost/success: ${before_cps:.4f} -> ${after_cps:.4f} "
            f"({pct(delta['cost_per_success_reduction'])} reduction)"
        )
    print(
        f"calls: model {baseline['model_calls']} -> {optimized['model_calls']}; "
        f"tools {baseline['tool_calls']} -> {optimized['tool_calls']}"
    )
    print(
        f"mean latency: {baseline['mean_latency_ms']:.0f} ms -> "
        f"{optimized['mean_latency_ms']:.0f} ms"
    )
    intervals = result["confidence"]["intervals"]

    def ci(name: str) -> str:
        """Render one optional confidence interval."""
        interval = intervals.get(name)
        return "n/a" if interval is None else f"{pct(interval[0])} to {pct(interval[1])}"

    if any(value is not None for value in intervals.values()):
        print(
            f"95% CI over {result['confidence']['task_clusters']} tasks: "
            f"tokens {ci('total_token_reduction')}; cost {ci('cost_reduction')}; "
            f"cost/success {ci('cost_per_success_reduction')}"
        )
    else:
        print(
            f"95% CI: n/a ({result['confidence'].get('note', 'insufficient data')})"
        )
    if result["outcomes"]["regressed_tasks"]:
        print("regressed tasks: " + ", ".join(result["outcomes"]["regressed_tasks"]))
    return 0

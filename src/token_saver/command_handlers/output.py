"""Output-policy, compaction, replay, and benchmark CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..output_benchmark import evaluate_output_manifest
from ..output_budget import calibrate_output_budgets
from ..output_processors import explain_processor
from ..output_telemetry import load_output_telemetry, output_telemetry_report
from ..output_quality import evaluate_quality_manifest
from ..output_saver import (
    build_output_policy,
    compact_output,
    compact_structured_result,
)




def output_telemetry_main(argv: list[str]) -> int:
    """Report local generation-budget telemetry without inferring task success."""
    parser = argparse.ArgumentParser(prog="token-saver output-telemetry")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--records",
        action="store_true",
        help="include recent content-free raw telemetry records",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    root = Path(args.path).resolve()
    report = output_telemetry_report(root)
    if args.records:
        report["records"] = load_output_telemetry(root)[-args.limit :]
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    summary = report["summary"]
    print("TOKEN SAVER OUTPUT TELEMETRY")
    print(f"path: {report['path']}")
    print(
        "turns: "
        f"{summary['turns']} total, {summary['measured_turns']} with usage, "
        f"{summary['api_failures']} API failures"
    )
    if summary["measured_turns"]:
        print(f"output tokens: {summary['output_tokens']:,}")
        if summary["mean_selected_budget"] is not None:
            print(f"mean selected budget: {summary['mean_selected_budget']:.1f}")
        if summary["mean_budget_utilization"] is not None:
            print(
                "mean budget utilization: "
                f"{100 * summary['mean_budget_utilization']:.1f}%"
            )
        if summary["target_met_rate"] is not None:
            print(f"soft target met: {100 * summary['target_met_rate']:.1f}%")
    limits = report["evidence_limits"]
    print("evidence: turn completion only; no task-success or quality inference")
    if args.records:
        print(f"records included: {len(report['records'])}")
    return 0


def output_calibrate_main(argv: list[str]) -> int:
    """Build a quality-gated adaptive output-budget calibration artifact."""
    parser = argparse.ArgumentParser(prog="token-saver output-calibrate")
    parser.add_argument("manifest", help="paired agent-run JSON with blind quality scores")
    parser.add_argument(
        "--margin",
        type=float,
        default=1.15,
        help="safety margin applied above observed p90 output tokens (default: 1.15)",
    )
    parser.add_argument(
        "--out",
        help="optional JSON artifact path; stdout is used when omitted",
    )
    args = parser.parse_args(argv)
    try:
        result = calibrate_output_budgets(Path(args.manifest), margin=args.margin)
        rendered = json.dumps(result, indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0

def output_policy_main(argv: list[str]) -> int:
    """Run the output policy command."""
    parser = argparse.ArgumentParser(prog="token-saver output-policy")
    parser.add_argument(
        "--mode",
        choices=("terse", "normal", "detailed"),
        default="normal",
    )
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument(
        "--task",
        choices=("general", "coding", "debugging", "review", "explanation", "planning"),
        default="general",
        help="adapt the generation policy and default budget to the task type",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = build_output_policy(args.mode, args.max_tokens, args.task)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(policy.to_dict(), indent=2))
    else:
        print(policy.instructions)
    return 0


def output_save_main(argv: list[str]) -> int:
    """Run the output save command."""
    parser = argparse.ArgumentParser(prog="token-saver output-save")
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="response file or - for stdin",
    )
    parser.add_argument(
        "--mode",
        choices=("terse", "normal", "detailed"),
        default="normal",
    )
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument(
        "--enforce-budget",
        action="store_true",
        help="trim prose to the budget; fenced code/diffs are always preserved",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        help="parse JSON input and emit compact machine-to-machine JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit result metadata as JSON",
    )
    args = parser.parse_args(argv)
    try:
        text = (
            sys.stdin.read()
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8")
        )
        if args.structured:
            text = compact_structured_result(json.loads(text))
        result = compact_output(
            text,
            mode=args.mode,
            max_tokens=args.max_tokens,
            enforce_budget=args.enforce_budget,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        sys.stdout.write(result.text)
        if result.text and not result.text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def output_benchmark_main(argv: list[str]) -> int:
    """Run the output benchmark command."""
    parser = argparse.ArgumentParser(prog="token-saver output-benchmark")
    parser.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        result = evaluate_output_manifest(Path(args.manifest))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def output_explain_main(argv: list[str]) -> int:
    """Run the output explain command."""
    parser = argparse.ArgumentParser(prog="token-saver output-explain")
    parser.add_argument("command")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument(
        "--sample",
        help="optional captured output used for failure detection",
    )
    args = parser.parse_args(argv)
    sample = ""
    if args.sample:
        try:
            sample = Path(args.sample).read_text(encoding="utf-8")
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    print(
        json.dumps(
            explain_processor(
                args.command,
                exit_code=args.exit_code,
                sample=sample,
            ),
            indent=2,
        )
    )
    return 0


def output_replay_main(argv: list[str]) -> int:
    """Run the output replay command."""
    parser = argparse.ArgumentParser(prog="token-saver output-replay")
    parser.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        result = evaluate_quality_manifest(Path(args.manifest))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["summary"]["failed"] else 0

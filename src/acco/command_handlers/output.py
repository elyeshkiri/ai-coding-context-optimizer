"""Output-policy, compaction, replay, and benchmark CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..output_benchmark import evaluate_output_manifest
from ..output_budget import calibrate_output_budgets
from ..output_effectiveness import (
    EffectivenessPricing,
    evaluate_output_effectiveness,
)
from ..output_processors import explain_processor
from ..processor_mining import mine_transcripts
from ..sessions import transcript_paths
from ..output_telemetry import load_output_telemetry, output_telemetry_report
from ..output_quality import evaluate_quality_manifest, quality_definition_hash
from ..output_saver import (
    build_output_policy,
    compact_output,
    compact_structured_result,
)





def corpus_analyze_main(argv: list[str]) -> int:
    """Mine real Claude transcripts for the highest-cost generic processor gaps."""
    parser = argparse.ArgumentParser(prog="acco corpus-analyze")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--all-projects", action="store_true")
    parser.add_argument("--min-tokens", type=int, default=100)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = transcript_paths(
            Path(args.path).resolve(),
            all_projects=args.all_projects,
        )
        report = mine_transcripts(
            paths,
            min_tokens=args.min_tokens,
            top=args.top,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("ACCO PROCESSOR CORPUS ANALYSIS")
    print(f"sessions: {report['sessions']}")
    print(f"bash calls: {report['bash_calls']}")
    print(f"output tokens: {report['total_output_tokens']:,}")
    coverage = report["specialized_coverage"]
    if coverage is None:
        print("specialized coverage: no eligible Bash output")
    else:
        print(f"specialized coverage: {coverage:.1%}")
    print("highest-cost generic families:")
    if not report["unsupported"]:
        print("  none in the selected corpus")
    for item in report["unsupported"]:
        print(
            f"  {item['output_tokens']:>9,} tok  "
            f"{item['calls']:>4} calls  {item['signature']}"
        )
    return 0


def output_effectiveness_main(argv: list[str]) -> int:
    """Join paired usage, success, quality, and budget evidence."""
    parser = argparse.ArgumentParser(prog="acco output-effectiveness")
    parser.add_argument("manifest")
    parser.add_argument("--fresh-input-per-million", type=float)
    parser.add_argument("--cache-creation-5m-per-million", type=float)
    parser.add_argument("--cache-creation-1h-per-million", type=float)
    parser.add_argument("--cache-creation-unknown-per-million", type=float)
    parser.add_argument("--cache-read-per-million", type=float)
    parser.add_argument("--output-per-million", type=float)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-publishable",
        action="store_true",
        help="exit 1 unless all success/quality/telemetry/cost publication gates pass",
    )
    args = parser.parse_args(argv)
    pricing = EffectivenessPricing(
        fresh_input_per_million=args.fresh_input_per_million,
        cache_creation_5m_per_million=args.cache_creation_5m_per_million,
        cache_creation_1h_per_million=args.cache_creation_1h_per_million,
        cache_creation_unknown_per_million=args.cache_creation_unknown_per_million,
        cache_read_per_million=args.cache_read_per_million,
        output_per_million=args.output_per_million,
    )
    supplied_rates = (
        pricing.fresh_input_per_million,
        pricing.cache_creation_5m_per_million,
        pricing.cache_creation_1h_per_million,
        pricing.cache_creation_unknown_per_million,
        pricing.cache_read_per_million,
        pricing.output_per_million,
    )
    if any(value is not None and value < 0 for value in supplied_rates):
        print("pricing values must be nonnegative", file=sys.stderr)
        return 2
    try:
        result = evaluate_output_effectiveness(
            Path(args.manifest),
            pricing=pricing,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        baseline = result["conditions"]["baseline"]
        optimized = result["conditions"]["acco"]
        reduction = result["delta"]["cost_per_success_reduction"]
        print(
            f"OUTPUT EFFECTIVENESS: {result['paired_trials']} paired trials "
            f"across {result['tasks']} tasks"
        )
        print(
            "success: "
            f"{baseline['success_rate'] * 100:.1f}% -> "
            f"{optimized['success_rate'] * 100:.1f}%"
        )
        if reduction is None:
            print("cost/success reduction: n/a")
        else:
            print(f"cost/success reduction: {reduction * 100:.1f}%")
        print(
            "quality: "
            + ("blind parity" if result["quality"]["blinded"] and result["quality"]["parity"]
               else "not publishable")
        )
        print(
            "telemetry: "
            f"{result['telemetry']['runs_with_policy_telemetry']}/"
            f"{result['telemetry']['optimized_runs']} optimized runs"
        )
        gate = result["publication_gate"]
        print("publication gate: " + ("PASS" if gate["passed"] else "FAIL"))
        if gate["blockers"]:
            print("blockers: " + ", ".join(gate["blockers"]))

    if args.require_publishable and not result["publication_gate"]["passed"]:
        return 1
    return 0


def output_telemetry_main(argv: list[str]) -> int:
    """Report local generation-budget telemetry without inferring task success."""
    parser = argparse.ArgumentParser(prog="acco output-telemetry")
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
    print("ACCO OUTPUT TELEMETRY")
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
    print("evidence: turn completion only; no task-success or quality inference")
    if args.records:
        print(f"records included: {len(report['records'])}")
    return 0


def output_calibrate_main(argv: list[str]) -> int:
    """Build a quality-gated adaptive output-budget calibration artifact."""
    parser = argparse.ArgumentParser(prog="acco output-calibrate")
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
    parser = argparse.ArgumentParser(prog="acco output-policy")
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
    parser = argparse.ArgumentParser(prog="acco output-save")
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
    parser = argparse.ArgumentParser(prog="acco output-benchmark")
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
    parser = argparse.ArgumentParser(prog="acco output-explain")
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
    """Run output quality replay with optional immutable fixture validation."""
    parser = argparse.ArgumentParser(prog="acco output-replay")
    parser.add_argument("manifest")
    parser.add_argument("--require-frozen", action="store_true")
    parser.add_argument("--print-definition-hash", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.manifest)
    try:
        if args.print_definition_hash:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("quality manifest must be a JSON object")
            print(quality_definition_hash(payload))
            return 0
        result = evaluate_quality_manifest(
            path,
            require_frozen=args.require_frozen,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["summary"]["failed"] else 0

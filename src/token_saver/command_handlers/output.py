"""Output-policy, compaction, replay, and benchmark CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..output_benchmark import evaluate_output_manifest
from ..output_processors import explain_processor
from ..output_quality import evaluate_quality_manifest
from ..output_saver import (
    build_output_policy,
    compact_output,
    compact_structured_result,
)


def output_policy_main(argv: list[str]) -> int:
    """Run the output policy command."""
    parser = argparse.ArgumentParser(prog="token-saver output-policy")
    parser.add_argument(
        "--mode",
        choices=("terse", "normal", "detailed"),
        default="normal",
    )
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = build_output_policy(args.mode, args.max_tokens)
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

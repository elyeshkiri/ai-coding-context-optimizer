"""High-value command-line surfaces kept separate from the legacy CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluate import evaluate_manifest, ground_truth_hash
from .context_browser import browse_context
from .agent_eval import evaluate_agent_runs
from .feedback import record_feedback
from .host_validate import validate_host
from .impact import analyze_impact
from .patch_context import build_diff_context, review_patch
from .output_benchmark import evaluate_output_manifest
from .output_saver import build_output_policy, compact_output, compact_structured_result
from .serve import serve


def impact_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver impact")
    parser.add_argument("target", help="repository-relative file or symbol name")
    parser.add_argument("--path", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = analyze_impact(Path(args.path).resolve(), args.target)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"IMPACT: {args.target}")
        for match in payload["matched"]:
            suffix = f":{match['start_line']}" if match["start_line"] else ""
            print(f"= {match['path']}{suffix} {match['symbol'] or ''}".rstrip())
        for item in report.affected:
            symbol = f"::{item.symbol}" if item.symbol else ""
            print(f"{item.confidence:.2f} {item.path}{symbol} [{item.reason}]")
    return 0


def feedback_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver feedback")
    parser.add_argument("file")
    parser.add_argument("--path", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--useful", action="store_true")
    group.add_argument("--irrelevant", action="store_true")
    args = parser.parse_args(argv)
    scores = record_feedback(Path(args.path), args.file, useful=args.useful)
    normalized = args.file.replace("\\", "/").lstrip("./")
    print(json.dumps({"file": args.file, "score": scores[normalized]}))
    return 0


def evaluate_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver evaluate")
    parser.add_argument("manifest")
    parser.add_argument("--path", default=".")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument(
        "--require-holdout", action="store_true",
        help="require development-excluded holdout metadata and a valid frozen ground-truth hash",
    )
    parser.add_argument(
        "--print-ground-truth-hash", action="store_true",
        help="print the SHA-256 to freeze into protocol.ground_truth_sha256 without running tasks",
    )
    args = parser.parse_args(argv)
    manifest = Path(args.manifest)
    try:
        if args.print_ground_truth_hash:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be a JSON object")
            print(ground_truth_hash(payload))
            return 0
        result = evaluate_manifest(
            Path(args.path), manifest, args.max_tokens,
            require_holdout=args.require_holdout,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def agent_evaluate_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver agent-evaluate")
    parser.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        result = evaluate_agent_runs(Path(args.manifest))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def host_check_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver host-check")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--host", default="claude", help="host executable to inspect")
    parser.add_argument(
        "--live-evidence",
        help="host debug transcript proving updatedToolOutput acceptance",
    )
    parser.add_argument(
        "--require-ready", action="store_true",
        help="return nonzero unless hooks are configured and transport recovery passes",
    )
    parser.add_argument(
        "--require-live", action="store_true",
        help="return nonzero unless supplied host debug evidence verifies replacement acceptance",
    )
    args = parser.parse_args(argv)
    try:
        result = validate_host(
            Path(args.path),
            executable=args.host,
            live_evidence=Path(args.live_evidence) if args.live_evidence else None,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    if args.require_live and not result["live_verified"]:
        return 1
    if args.require_ready and not result["ready"]:
        return 1
    return 0


def serve_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver serve")
    parser.add_argument("path", nargs="?", default=".")
    args = parser.parse_args(argv)
    return serve(Path(args.path).resolve())


def _patch_args(prog: str, argv: list[str]):
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=6000)
    return parser.parse_args(argv)


def pack_diff_main(argv: list[str]) -> int:
    args = _patch_args("token-saver pack-diff", argv)
    try:
        result = build_diff_context(
            Path(args.path).resolve(), base=args.base, staged=args.staged,
            max_tokens=args.max_tokens,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        sys.stdout.write(result["context"])
        coverage = result["coverage"]
        print(
            f"\n# coverage: {len(coverage['selected'])}/{coverage['changed_files']} changed files "
            f"represented ({len(coverage['not_represented'])} not selected, "
            f"{len(coverage['excluded_by_policy'])} excluded by policy)"
        )
        if coverage["not_represented"]:
            print(f"# not represented: {', '.join(coverage['not_represented'][:10])}"
                  + (" …" if len(coverage["not_represented"]) > 10 else ""))
    return 0


def review_main(argv: list[str]) -> int:
    args = _patch_args("token-saver review", argv)
    try:
        result = review_patch(Path(args.path).resolve(), base=args.base, staged=args.staged)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"PATCH REVIEW ({len(result['files'])} files)")
        for item in result["files"]:
            print(f"{item['status']:>2} {item['path']} symbols={','.join(item['symbols']) or '-'}")
        for warning in result["warnings"]:
            print(f"! {warning['code']}: {warning.get('path') or warning.get('detail', '')}")
    return 0


def output_policy_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver output-policy")
    parser.add_argument("--mode", choices=("terse", "normal", "detailed"), default="normal")
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
    parser = argparse.ArgumentParser(prog="token-saver output-save")
    parser.add_argument("input", nargs="?", default="-", help="response file or - for stdin")
    parser.add_argument("--mode", choices=("terse", "normal", "detailed"), default="normal")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument(
        "--enforce-budget", action="store_true",
        help="trim prose to the budget; fenced code/diffs are always preserved",
    )
    parser.add_argument(
        "--structured", action="store_true",
        help="parse JSON input and emit compact machine-to-machine JSON",
    )
    parser.add_argument("--json", action="store_true", help="emit result metadata as JSON")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
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



def browse_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="token-saver browse")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--preview-tokens", type=int, default=350)
    parser.add_argument("--detail-tokens", type=int, default=1200)
    parser.add_argument("--show", type=int, help="print one candidate's detailed source view")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-changed-boost", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = browse_context(
            Path(args.path).resolve(),
            args.query,
            max_files=args.max_files,
            preview_tokens=args.preview_tokens,
            detail_tokens=args.detail_tokens,
            changed_boost=not args.no_changed_boost,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    def print_list() -> None:
        print(f"CONTEXT BROWSER: {report['query']}")
        for item in report["files"]:
            symbols = ", ".join(
                label.split(":", 1)[-1].rsplit("@", 1)[0]
                for label in item["symbols"]
            ) or "-"
            fuzzy = ", ".join(
                f"{source}->{value['term']} ({value['similarity']:.2f})"
                for source, value in item["fuzzy_corrections"].items()
            )
            suffix = f" fuzzy=[{fuzzy}]" if fuzzy else ""
            print(
                f"{item['rank']:>2}. {item['score']:>7.2f} {item['path']} "
                f"symbols=[{symbols}] tokens~{item['preview_tokens']}{suffix}"
            )

    print_list()
    if args.show is not None:
        if args.show < 1 or args.show > len(report["files"]):
            print("candidate number out of range", file=sys.stderr)
            return 2
        print()
        print(report["files"][args.show - 1]["detail"], end="")

    if args.interactive:
        while True:
            try:
                command = input("browse> ").strip()
            except EOFError:
                break
            if command in {"q", "quit", "exit"}:
                break
            if command in {"", "list", "ls"}:
                print_list()
                continue
            parts = command.split()
            if len(parts) == 2 and parts[0] in {"show", "s"} and parts[1].isdigit():
                selected = int(parts[1])
                if 1 <= selected <= len(report["files"]):
                    print(report["files"][selected - 1]["detail"], end="")
                else:
                    print("candidate number out of range")
                continue
            print("commands: list | show N | quit")
    return 0



def output_benchmark_main(argv: list[str]) -> int:
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

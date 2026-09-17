"""v0.9 command-line surfaces kept separate from the legacy CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluate import evaluate_manifest
from .agent_eval import evaluate_agent_runs
from .feedback import record_feedback
from .impact import analyze_impact
from .patch_context import build_diff_context, review_patch
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
        help="require frozen ground truth and development-excluded holdout metadata",
    )
    args = parser.parse_args(argv)
    try:
        result = evaluate_manifest(
            Path(args.path), Path(args.manifest), args.max_tokens,
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

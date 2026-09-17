"""v0.9 command-line surfaces kept separate from the legacy CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluate import evaluate_manifest
from .feedback import record_feedback
from .impact import analyze_impact
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
    args = parser.parse_args(argv)
    try:
        result = evaluate_manifest(Path(args.path), Path(args.manifest), args.max_tokens)
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

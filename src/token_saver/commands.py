"""High-value command-line surfaces kept separate from the legacy CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluate import evaluate_manifest, ground_truth_hash
from .agent_eval import evaluate_agent_runs
from .feedback import record_feedback
from .host_validate import validate_host
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
        for item in payload if False else result["files"]:
            print(f"{item['status']:>2} {item['path']} symbols={','.join(item['symbols']) or '-'}")
        for warning in result["warnings"]:
            print(f"! {warning['code']}: {warning.get('path') or warning.get('detail', '')}")
    return 0

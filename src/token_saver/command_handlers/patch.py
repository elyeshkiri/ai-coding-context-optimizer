"""Patch-context and review CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..patch_context import build_diff_context, review_patch


def _patch_args(prog: str, argv: list[str]):
    """Parse the shared patch-context command arguments."""
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=6000)
    return parser.parse_args(argv)


def pack_diff_main(argv: list[str]) -> int:
    """Run the pack diff command."""
    args = _patch_args("token-saver pack-diff", argv)
    try:
        result = build_diff_context(
            Path(args.path).resolve(),
            base=args.base,
            staged=args.staged,
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
            print(
                f"# not represented: {', '.join(coverage['not_represented'][:10])}"
                + (" …" if len(coverage["not_represented"]) > 10 else "")
            )
    return 0


def review_main(argv: list[str]) -> int:
    """Run the review command."""
    args = _patch_args("token-saver review", argv)
    try:
        result = review_patch(
            Path(args.path).resolve(),
            base=args.base,
            staged=args.staged,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"PATCH REVIEW ({len(result['files'])} files)")
        for item in result["files"]:
            print(
                f"{item['status']:>2} {item['path']} "
                f"symbols={','.join(item['symbols']) or '-'}"
            )
        for warning in result["warnings"]:
            print(
                f"! {warning['code']}: "
                f"{warning.get('path') or warning.get('detail', '')}"
            )
    return 0

#!/usr/bin/env python3
"""Run or inspect the frozen no-identifier-leakage semantic holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from token_saver.semantic_holdout import (
    evaluate_semantic_holdout,
    merge_semantic_holdout_results,
    query_freeze_hash,
    semantic_ground_truth_hash,
    validate_semantic_holdout,
)


def _print_progress(message: str) -> None:
    """Write one immediately visible holdout progress record to stderr."""
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    """Run the semantic holdout command-line harness."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        nargs="?",
        default="benchmarks/semantic-holdout-13.frozen.json",
    )
    parser.add_argument("--output")
    parser.add_argument(
        "--repository",
        action="append",
        default=[],
        help="evaluate only one repository alias; may be repeated",
    )
    parser.add_argument(
        "--merge-input",
        action="append",
        default=[],
        help="merge repository-sharded result JSON; may be repeated",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="emit task/repository progress to stderr",
    )
    parser.add_argument("--print-query-freeze-hash", action="store_true")
    parser.add_argument("--print-ground-truth-hash", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    if args.print_query_freeze_hash:
        freeze_name = payload.get("protocol", {}).get("query_freeze_file")
        if not isinstance(freeze_name, str):
            raise SystemExit("manifest is missing protocol.query_freeze_file")
        freeze = json.loads(
            (manifest.parent / freeze_name).read_text(encoding="utf-8")
        )
        print(query_freeze_hash(freeze))
        return 0

    if args.print_ground_truth_hash:
        print(semantic_ground_truth_hash(payload))
        return 0

    if args.validate_only:
        print(json.dumps(validate_semantic_holdout(payload, manifest), indent=2))
        return 0

    if args.merge_input:
        parts = [
            json.loads(Path(value).read_text(encoding="utf-8"))
            for value in args.merge_input
        ]
        result = merge_semantic_holdout_results(parts, manifest)
    else:
        progress = _print_progress if args.progress else None
        result = evaluate_semantic_holdout(
            manifest.parent,
            manifest,
            repositories=set(args.repository) if args.repository else None,
            progress=progress,
        )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

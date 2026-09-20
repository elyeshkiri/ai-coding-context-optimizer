#!/usr/bin/env python3
"""Run or inspect the frozen no-identifier-leakage semantic holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from token_saver.semantic_holdout import (
    evaluate_semantic_holdout,
    query_freeze_hash,
    semantic_ground_truth_hash,
    validate_semantic_holdout,
)


def main() -> int:
    """Run the semantic holdout command-line harness."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        nargs="?",
        default="benchmarks/semantic-holdout-13.frozen.json",
    )
    parser.add_argument("--output")
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

    result = evaluate_semantic_holdout(manifest.parent, manifest)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

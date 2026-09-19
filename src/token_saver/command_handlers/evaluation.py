"""Context and agent evaluation CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agent_eval import evaluate_agent_runs
from ..evaluate import evaluate_manifest, ground_truth_hash


def evaluate_main(argv: list[str]) -> int:
    """Run the evaluate command."""
    parser = argparse.ArgumentParser(prog="token-saver evaluate")
    parser.add_argument("manifest")
    parser.add_argument("--path", default=".")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument(
        "--require-holdout",
        action="store_true",
        help="require development-excluded holdout metadata and a valid frozen ground-truth hash",
    )
    parser.add_argument(
        "--print-ground-truth-hash",
        action="store_true",
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
            Path(args.path),
            manifest,
            args.max_tokens,
            require_holdout=args.require_holdout,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def agent_evaluate_main(argv: list[str]) -> int:
    """Run the agent evaluate command."""
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

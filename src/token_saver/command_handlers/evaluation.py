"""Context and agent evaluation CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agent_eval import evaluate_agent_runs
from ..evaluate import evaluate_manifest, ground_truth_hash
from ..ranking_regression import (
    build_ranking_snapshot,
    compare_ranking_snapshots,
    load_ranking_snapshot,
    regression_violations,
    render_ranking_diff_markdown,
)


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


def ranking_snapshot_main(argv: list[str]) -> int:
    """Capture ranking traces for an evaluation-style task manifest."""
    parser = argparse.ArgumentParser(prog="token-saver ranking-snapshot")
    parser.add_argument("manifest")
    parser.add_argument("--path", default=".")
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--graph-hops", type=int, default=1)
    parser.add_argument("--closure-items", type=int, default=20)
    parser.add_argument("--embeddings", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        snapshot = build_ranking_snapshot(
            Path(args.path),
            Path(args.manifest),
            max_files=args.max_files,
            graph_hops=args.graph_hops,
            closure_max_items=args.closure_items,
            embeddings=args.embeddings,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    rendered = json.dumps(snapshot, indent=2)
    if args.out:
        try:
            Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        print(rendered)
    return 0


def ranking_diff_main(argv: list[str]) -> int:
    """Compare two ranking snapshots and attribute expected-file movement."""
    parser = argparse.ArgumentParser(prog="token-saver ranking-diff")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 when an expected file disappears or drops too far",
    )
    parser.add_argument(
        "--allowed-rank-drop",
        type=int,
        default=0,
        help="largest downward rank movement allowed by --fail-on-regression",
    )
    args = parser.parse_args(argv)
    try:
        baseline = load_ranking_snapshot(Path(args.baseline))
        candidate = load_ranking_snapshot(Path(args.candidate))
        report = compare_ranking_snapshots(baseline, candidate)
        violations = regression_violations(
            report,
            allowed_rank_drop=args.allowed_rank_drop,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        payload = dict(report)
        payload["violations"] = violations
        print(json.dumps(payload, indent=2))
    elif args.markdown:
        print(render_ranking_diff_markdown(report))
    else:
        summary = report["summary"]
        print(
            "RANKING DIFF: "
            f"{summary['regressed_files']} regressed, "
            f"{summary['improved_files']} improved, "
            f"{summary['missing_in_candidate']} missing"
        )
        for task in report["tasks"]:
            interesting = [
                item
                for item in task["files"]
                if item["regression"] or item["improvement"]
            ]
            if not interesting:
                continue
            print(f"\n{task['id']}: {task['query']}")
            for item in interesting:
                before = item["baseline_rank"]
                after = item["candidate_rank"]
                direction = "REGRESSION" if item["regression"] else "IMPROVEMENT"
                print(f"  {direction}: {item['path']} rank {before} -> {after}")
                for change in item["stage_changes"][:5]:
                    if abs(change["delta"]) <= 1e-12:
                        continue
                    print(
                        f"    {change['stage']:<24} "
                        f"{change['delta']:+.3f} "
                        f"({change['baseline']:.3f} -> {change['candidate']:.3f})"
                    )

    if args.fail_on_regression and violations:
        return 1
    return 0

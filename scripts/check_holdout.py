#!/usr/bin/env python3
"""Run a frozen external holdout and enforce its regression floor.

The self-benchmark is saturated at 100%, so it cannot detect a ranking
regression. This runs a real frozen holdout against pinned external
repositories and fails when recall drops below the recorded floor.

Clones are cached by revision, so repeated local runs are cheap:

    python scripts/check_holdout.py benchmarks/holdout-external.floor.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"command failed: {' '.join(args)}\n{proc.stderr.strip()}"
        )


def ensure_clone(dest: Path, url: str, revision: str) -> None:
    """Fetch exactly the pinned revision, reusing an existing checkout."""
    if dest.exists():
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if head == revision:
            print(f"  {dest.name}: already at {revision[:7]}")
            return
        print(f"  {dest.name}: wrong revision {head[:7]}, refetching")
    else:
        dest.mkdir(parents=True, exist_ok=True)
        _run("git", "-C", str(dest), "init", "-q")
        _run("git", "-C", str(dest), "remote", "add", "origin", url)
    # Fetching the single pinned commit avoids pulling full history for a
    # benchmark that only ever reads one tree.
    _run("git", "-C", str(dest), "fetch", "-q", "--depth", "1", "origin", revision)
    _run("git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD")
    print(f"  {dest.name}: checked out {revision[:7]}")


def _floor_failures(summary: dict, floor: dict) -> list[str]:
    """Return every metric that has fallen below its recorded regression floor."""
    failures = []
    for key, minimum in floor.items():
        if key not in summary:
            failures.append(f"{key}: missing from evaluation summary")
            continue
        actual = float(summary[key])
        if actual < float(minimum):
            failures.append(f"{key}: {actual:.3f} < floor {float(minimum):.3f}")
    return failures


def _ratcheted_floor(summary: dict, floor: dict) -> dict[str, float]:
    """Raise improved floors without ever allowing an existing floor to decrease."""
    failures = _floor_failures(summary, floor)
    if failures:
        raise ValueError("; ".join(failures))
    return {
        key: max(float(minimum), round(float(summary[key]), 3))
        for key, minimum in floor.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="holdout floor spec JSON")
    parser.add_argument(
        "--update-floor", action="store_true",
        help="raise the floor to measured improvements; never lowers a floor",
    )
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    manifest = REPO_ROOT / spec["manifest"]
    max_tokens = int(spec.get("max_tokens", 6000))

    print("Preparing pinned holdout repositories:")
    for name, repo in spec["repositories"].items():
        ensure_clone(manifest.parent / name, repo["url"], repo["revision"])

    # Imported here so clone failures surface before an import error would.
    from token_saver.evaluate import evaluate_manifest

    result = evaluate_manifest(
        REPO_ROOT, manifest, max_tokens=max_tokens, require_holdout=True,
    )
    summary = result["summary"]

    print(f"\nHoldout: {manifest.name}  ({summary['task_count']} tasks)")
    print(f"  ground truth sha256: {result['ground_truth_sha256']}")
    for task in result["tasks"]:
        scoped = task.get("symbol_recall_in_expected_files")
        mark = (
            "ok  "
            if task["file_recall"] == 1.0
            and task["symbol_recall"] == 1.0
            and (scoped is None or scoped == 1.0)
            else "MISS"
        )
        scoped_text = "" if scoped is None else f" scoped={scoped:.3f}"
        print(
            f"  {mark} {task['id']:<22} file={task['file_recall']:.3f} "
            f"symbol={task['symbol_recall']:.3f}{scoped_text}"
        )

    failures = _floor_failures(summary, spec["floor"])

    if args.update_floor:
        if failures:
            print("\nREFUSING TO LOWER FLOOR: " + "; ".join(failures))
            return 1
        spec["floor"] = _ratcheted_floor(summary, spec["floor"])
        args.spec.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"\nfloor ratcheted to {spec['floor']}")
        return 0

    print()
    for key, floor in spec["floor"].items():
        actual = float(summary[key])
        target = spec.get("target", {}).get(key)
        status = "PASS" if actual >= float(floor) else "FAIL"
        suffix = ""
        if target is not None and actual < float(target):
            suffix = f"  (below target {float(target):.3f} — see spec _note)"
        elif target is not None and actual > float(floor):
            suffix = "  (above floor — consider ratcheting with --update-floor)"
        print(
            f"  {status} {key}: {actual:.3f} >= floor {float(floor):.3f}{suffix}"
        )

    if failures:
        print("\nREGRESSION: " + "; ".join(failures))
        print(
            "This holdout is burned: fix the ranking cause, never tune "
            "against this suite to move the number."
        )
        return 1
    print("\nHoldout floor held.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

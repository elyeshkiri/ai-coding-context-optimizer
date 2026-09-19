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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="holdout floor spec JSON")
    parser.add_argument(
        "--update-floor", action="store_true",
        help="rewrite the floor to the measured result (use only when "
             "deliberately ratcheting after a verified improvement)",
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
        mark = "ok  " if task["file_recall"] == 1.0 and task["symbol_recall"] == 1.0 else "MISS"
        print(
            f"  {mark} {task['id']:<22} file={task['file_recall']:.3f} "
            f"symbol={task['symbol_recall']:.3f}"
        )

    if args.update_floor:
        spec["floor"] = {
            key: round(summary[key], 3) for key in spec["floor"]
        }
        args.spec.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"\nfloor updated to {spec['floor']}")
        return 0

    failures = []
    print()
    for key, floor in spec["floor"].items():
        actual = summary[key]
        target = spec.get("target", {}).get(key)
        status = "PASS" if actual >= floor else "FAIL"
        suffix = ""
        if target is not None and actual < target:
            suffix = f"  (below target {target:.3f} — see spec _note)"
        elif target is not None and actual > floor:
            suffix = "  (above floor — consider ratcheting with --update-floor)"
        print(f"  {status} {key}: {actual:.3f} >= floor {floor:.3f}{suffix}")
        if actual < floor:
            failures.append(f"{key}: {actual:.3f} < floor {floor:.3f}")

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

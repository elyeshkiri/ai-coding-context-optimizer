#!/usr/bin/env python3
"""Merge sharded frozen experiment results into one publishable manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acco.experiment import build_schedule, validate_suite


META_KEYS = (
    "suite_version",
    "protocol",
    "design",
    "repositories",
    "runner",
    "tasks",
    "quality_grader",
    "evidence",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument("output")
    parser.add_argument("shards", nargs="+")
    args = parser.parse_args()

    suite_path = Path(args.suite).resolve()
    suite = validate_suite(suite_path, require_frozen=True, require_broad=True)
    output = Path(args.output).resolve()

    merged = {key: suite[key] for key in META_KEYS if key in suite}
    merged["runs"] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in args.shards:
        path = Path(raw).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit(f"{path}: shard must be a JSON object")
        for key in META_KEYS:
            if payload.get(key) != suite.get(key):
                raise SystemExit(f"{path}: frozen metadata differs at {key}")
        for run in payload.get("runs", []):
            if not isinstance(run, dict):
                raise SystemExit(f"{path}: run must be an object")
            key = (
                str(run.get("task", "")),
                str(run.get("trial", "")),
                str(run.get("condition", "")),
            )
            if key in seen:
                raise SystemExit(f"duplicate run across shards: {key}")
            seen.add(key)
            merged["runs"].append(run)

    expected = {
        (str(item["task"]), str(item["trial"]), str(item["condition"]))
        for item in build_schedule(suite)
    }
    missing = sorted(expected - seen)
    extra = sorted(seen - expected)
    if missing or extra:
        raise SystemExit(
            f"incomplete shard set: missing={missing[:10]} extra={extra[:10]} "
            f"(expected {len(expected)}, found {len(seen)})"
        )

    merged["runs"].sort(
        key=lambda run: (
            str(run["task"]),
            int(run["trial"]),
            str(run["condition"]),
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"merged {len(merged['runs'])} runs -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

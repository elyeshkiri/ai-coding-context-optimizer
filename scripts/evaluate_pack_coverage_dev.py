#!/usr/bin/env python3
"""Evaluate pack coverage on an already-burned semantic holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from acco.pack import build_context_pack
from acco.repo_index import build_index
from acco.semantic_holdout import validate_semantic_holdout


def _revision(root: Path) -> str | None:
    """Return the current git revision."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _recall(expected: set[str], selected: list[str]) -> float:
    """Return file recall."""
    return len(expected & set(selected)) / len(expected) if expected else 1.0


def main() -> int:
    """Run lexical pack coverage on one or more burned-suite repositories."""
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--repository", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    validation = validate_semantic_holdout(payload, manifest)
    selected = set(args.repository)
    specs = payload["repositories"]
    indexes = {}
    revisions = {}
    rows = []

    for task in payload["tasks"]:
        if not bool(task.get("eligible", True)):
            continue
        alias = str(task["repository"])
        if selected and alias not in selected:
            continue
        spec = specs[alias]
        root = (manifest.parent / str(spec["path"])).resolve()
        if root not in indexes:
            actual = _revision(root)
            expected_revision = str(spec["revision"])
            if actual != expected_revision:
                raise SystemExit(
                    f"{alias}: revision mismatch {actual!r} != {expected_revision!r}"
                )
            indexes[root] = build_index(root)
            revisions[alias] = actual
        expected = {
            str(value).replace("\\", "/")
            for value in task.get("files", [])
        }
        pack = build_context_pack(
            root,
            str(task["query"]),
            max_tokens=int(task.get("max_tokens", payload.get("max_tokens", 6000))),
            max_files=int(task.get("max_files", payload.get("max_files", 12))),
            changed_boost=False,
            feedback_boost=False,
            index=indexes[root],
            embeddings=False,
            cache_enabled=False,
        )
        rows.append({
            "id": task["id"],
            "repository": alias,
            "expected_files": sorted(expected),
            "selected_files": list(pack.selected_files),
            "selected_count": len(pack.selected_files),
            "file_recall": _recall(expected, pack.selected_files),
            "estimated_tokens": pack.estimated_tokens,
        })

    out = {
        "suite": "semantic-holdout-16",
        "development_evidence_only": True,
        "protocol": validation,
        "repositories": revisions,
        "tasks": rows,
    }
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

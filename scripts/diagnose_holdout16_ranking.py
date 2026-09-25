#!/usr/bin/env python3
"""Decompose burned semantic holdout ranking quality from pack-budget effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from acco.pack import build_context_pack, rank_files
from acco.repo_index import build_index
from acco.semantic_holdout import (
    _trivial_lexical_files,
    validate_semantic_holdout,
)


def _revision(root: Path) -> str | None:
    """Return the checked-out git revision when available."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _recall(expected: set[str], selected: list[str]) -> float:
    """Return file recall for one ordered selection."""
    if not expected:
        return 1.0
    return len(expected & set(selected)) / len(expected)


def _task(root: Path, index, task: dict, payload: dict) -> dict:
    """Return rank-vs-pack diagnostics for one burned task."""
    query = str(task["query"])
    expected = {
        str(value).replace("\\", "/")
        for value in task.get("files", [])
    }
    max_tokens = int(task.get("max_tokens", payload.get("max_tokens", 6000)))
    max_files = int(task.get("max_files", payload.get("max_files", 12)))

    pack = build_context_pack(
        root,
        query,
        max_tokens=max_tokens,
        max_files=max_files,
        changed_boost=False,
        feedback_boost=False,
        index=index,
        embeddings=False,
        cache_enabled=False,
    )
    plan = pack.retrieval_plan
    traced = rank_files(
        root,
        query,
        changed_boost=False,
        feedback_boost=False,
        index=index,
        embeddings=False,
        graph_hops=int(plan["graph_hops"]),
        closure_max_items=int(plan["closure_items"]),
        seed_limit=int(plan["seed_limit"]),
        trace_scores=True,
    )
    pack_order = [item.rel for item in pack.ranked]
    trace_order = [item.rel for item in traced]
    if pack_order != trace_order:
        raise RuntimeError("diagnostic traced ranking does not match pack ranking")

    trivial = _trivial_lexical_files(index, query, max_files=max_files)
    ranked_top = pack_order[:max_files]
    packed_count = len(pack.selected_files)
    rank_at_pack_count = ranked_top[:packed_count]
    trivial_at_pack_count = trivial[:packed_count]
    by_rel = {
        item.rel: {
            "rank": rank,
            "score": item.score,
            "term_hits": item.term_hits,
            "reasons": list(item.reasons),
            "score_trace": [event.to_dict() for event in item.score_trace],
        }
        for rank, item in enumerate(traced, start=1)
    }

    expected_diagnostics = {}
    for rel in sorted(expected):
        expected_diagnostics[rel] = {
            **by_rel.get(rel, {"rank": None, "score": None, "term_hits": 0,
                               "reasons": [], "score_trace": []}),
            "packed": rel in pack.selected_files,
            "rank12": rel in ranked_top,
            "trivial12": rel in trivial,
        }

    return {
        "id": task["id"],
        "repository": task["repository"],
        "expected_files": sorted(expected),
        "pack_selected": list(pack.selected_files),
        "pack_selected_count": packed_count,
        "pack_recall": _recall(expected, pack.selected_files),
        "acco_rank12": ranked_top,
        "acco_rank12_recall": _recall(expected, ranked_top),
        "acco_rank_at_pack_count": rank_at_pack_count,
        "acco_rank_at_pack_count_recall": _recall(expected, rank_at_pack_count),
        "trivial_rank12": trivial,
        "trivial_rank12_recall": _recall(expected, trivial),
        "trivial_at_pack_count": trivial_at_pack_count,
        "trivial_at_pack_count_recall": _recall(expected, trivial_at_pack_count),
        "expected": expected_diagnostics,
        "top12_details": [
            {"rel": rel, **by_rel[rel]}
            for rel in ranked_top
        ],
        "retrieval_plan": plan,
        "estimated_tokens": pack.estimated_tokens,
    }


def main() -> int:
    """Run diagnostics against one or more repositories from burned #16."""
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--repository", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    validation = validate_semantic_holdout(payload, manifest)
    selected = set(args.repository)
    specs = payload.get("repositories", {})
    indexes = {}
    revisions = {}
    rows = []

    for task in payload.get("tasks", []):
        if not isinstance(task, dict) or not bool(task.get("eligible", True)):
            continue
        alias = str(task.get("repository"))
        if selected and alias not in selected:
            continue
        spec = specs.get(alias)
        if not isinstance(spec, dict):
            raise SystemExit(f"missing repository spec for {alias}")
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
        rows.append(_task(root, indexes[root], task, payload))

    result = {
        "suite": "semantic-holdout-16",
        "development_evidence_only": True,
        "protocol": validation,
        "repositories": revisions,
        "tasks": rows,
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

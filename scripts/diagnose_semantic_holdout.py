#!/usr/bin/env python3
"""Diagnose semantic reranking changes on an already-burned frozen holdout.\n\nDevelopment evidence only; never use this mode to claim fresh generalization.\n"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from acco.pack import build_context_pack
from acco.repo_index import build_index
from acco.semantic_holdout import validate_semantic_holdout

_SEMANTIC_STAGES = {
    "hybrid-semantic",
    "semantic-graph",
    "semantic-artifact-authority",
    "semantic-peer",
}


def _revision(root: Path) -> str | None:
    """Return the checked-out Git revision when available."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _snapshot(item, rank: int) -> dict:
    """Return ranking evidence for one file without source content."""
    semantic_events = [
        event.to_dict()
        for event in item.score_trace
        if event.stage in _SEMANTIC_STAGES
    ]
    first_semantic = next(
        (
            event
            for event in item.score_trace
            if event.stage in _SEMANTIC_STAGES
        ),
        None,
    )
    return {
        "rank": rank,
        "score": item.score,
        "pre_semantic_score": (
            first_semantic.before if first_semantic is not None else item.score
        ),
        "semantic_delta": sum(event["delta"] for event in semantic_events),
        "term_hits": item.term_hits,
        "reasons": list(item.reasons),
        "semantic_events": semantic_events,
        "semantic_ranges": [list(value) for value in item.semantic_ranges],
    }


def _by_rel(ranked) -> dict[str, tuple[int, object]]:
    """Map relative path to one-based rank and ranked-file object."""
    return {
        item.rel: (rank, item)
        for rank, item in enumerate(ranked, start=1)
    }


def _task_diagnostic(repo_root: Path, index, task: dict, payload: dict) -> dict:
    """Compare one frozen task before and after semantic reranking."""
    query = str(task["query"])
    max_tokens = int(task.get("max_tokens", payload.get("max_tokens", 6000)))
    max_files = int(task.get("max_files", payload.get("max_files", 12)))
    common = {
        "max_tokens": max_tokens,
        "max_files": max_files,
        "changed_boost": False,
        "feedback_boost": False,
        "index": index,
        "cache_enabled": False,
    }
    lexical_pack = build_context_pack(repo_root, query, embeddings=False, **common)
    semantic_pack = build_context_pack(repo_root, query, embeddings=True, **common)
    lexical = _by_rel(lexical_pack.ranked)
    semantic = _by_rel(semantic_pack.ranked)
    lexical_selected = set(lexical_pack.selected_files)
    semantic_selected = set(semantic_pack.selected_files)
    expected = {
        str(value).replace("\\", "/")
        for value in task.get("files", [])
    }
    entered = semantic_selected - lexical_selected
    exited = lexical_selected - semantic_selected
    interesting = sorted(expected | entered | exited)
    files = {}
    for rel in interesting:
        item = {"expected": rel in expected}
        if rel in lexical:
            rank, ranked_item = lexical[rel]
            item["lexical"] = _snapshot(ranked_item, rank)
        if rel in semantic:
            rank, ranked_item = semantic[rel]
            item["semantic"] = _snapshot(ranked_item, rank)
        item["lexical_selected"] = rel in lexical_selected
        item["semantic_selected"] = rel in semantic_selected
        files[rel] = item
    return {
        "id": task.get("id"),
        "repository": task.get("repository"),
        "query": query,
        "expected_files": sorted(expected),
        "lexical_selected": lexical_pack.selected_files,
        "semantic_selected": semantic_pack.selected_files,
        "entered": sorted(entered),
        "exited": sorted(exited),
        "files": files,
    }


def main() -> int:
    """Run diagnostics for one or more repositories in a burned suite."""
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--repository", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    validation = validate_semantic_holdout(payload, manifest)
    selected = set(args.repository)
    repositories = payload.get("repositories", {})
    indexes = {}
    revisions = {}
    tasks = []

    for task in payload.get("tasks", []):
        if not isinstance(task, dict) or not bool(task.get("eligible", True)):
            continue
        alias = task.get("repository")
        if selected and alias not in selected:
            continue
        spec = repositories.get(alias)
        if not isinstance(spec, dict):
            raise SystemExit(f"missing repository spec for {alias!r}")
        repo_root = (manifest.parent / str(spec["path"])).resolve()
        if repo_root not in indexes:
            revision = _revision(repo_root)
            expected_revision = spec.get("revision")
            if expected_revision and revision != expected_revision:
                raise SystemExit(
                    f"{alias}: revision mismatch {revision!r} != {expected_revision!r}"
                )
            indexes[repo_root] = build_index(repo_root)
            revisions[str(alias)] = revision
        tasks.append(
            _task_diagnostic(repo_root, indexes[repo_root], task, payload)
        )

    result = {
        "suite": manifest.name.removesuffix(".frozen.json"),
        "development_evidence_only": True,
        "protocol": validation,
        "repositories": revisions,
        "tasks": tasks,
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

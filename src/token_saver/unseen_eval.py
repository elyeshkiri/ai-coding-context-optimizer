"""Evaluation harness for fresh repositories/tasks with frozen ground truth.

Unlike the built-in self-benchmark, this suite accepts multiple repository paths
and refuses to run as a publishable/frozen evaluation unless the independently
written task definitions match a recorded SHA-256.  This makes accidental
post-hoc tuning visible instead of silently moving the target.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .pack import build_context_pack
from .repo_index import build_index


def _recall(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 1.0


def _ground_truth_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    normalized = []
    for position, raw in enumerate(tasks, start=1):
        if not isinstance(raw, dict):
            continue
        normalized.append({
            "id": raw.get("id", position),
            "repo": raw.get("repo", "."),
            "query": raw.get("query", ""),
            "files": sorted(str(value) for value in raw.get("files", []) if isinstance(value, str)),
            "symbols": sorted(str(value) for value in raw.get("symbols", []) if isinstance(value, str)),
            "max_tokens": int(raw.get("max_tokens", payload.get("max_tokens", 6000))),
        })
    return {
        "suite_version": int(payload.get("suite_version", 1)),
        "frozen_at": payload.get("frozen_at"),
        "tasks": normalized,
    }


def ground_truth_hash(payload: dict[str, Any]) -> str:
    """Stable hash of only the task definitions and expected evidence."""
    encoded = json.dumps(
        _ground_truth_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_unseen_suite(
    manifest: Path,
    *,
    require_frozen: bool = True,
    adaptive_budget: bool = True,
    typescript_semantic: bool = False,
) -> dict[str, Any]:
    manifest = manifest.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unseen manifest must be a JSON object")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("unseen manifest must contain a non-empty 'tasks' list")

    computed_hash = ground_truth_hash(payload)
    declared_hash = payload.get("ground_truth_sha256")
    frozen_at = payload.get("frozen_at")
    if require_frozen:
        if not isinstance(frozen_at, str) or not frozen_at.strip():
            raise ValueError("frozen unseen evaluation requires a non-empty 'frozen_at' field")
        if not isinstance(declared_hash, str) or declared_hash != computed_hash:
            raise ValueError(
                "ground truth is not frozen or changed; set ground_truth_sha256 to " + computed_hash
            )

    results: list[dict[str, Any]] = []
    manifest_dir = manifest.parent
    default_budget = int(payload.get("max_tokens", 6000))
    for position, raw in enumerate(tasks, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"task {position} must be an object")
        repo_value = str(raw.get("repo", "."))
        repo = Path(repo_value).expanduser()
        if not repo.is_absolute():
            repo = (manifest_dir / repo).resolve()
        else:
            repo = repo.resolve()
        if not repo.is_dir():
            raise ValueError(f"task {raw.get('id', position)} repository not found: {repo}")

        query = str(raw.get("query", ""))
        expected_files = {str(value).replace("\\", "/") for value in raw.get("files", [])}
        expected_symbols = {str(value) for value in raw.get("symbols", [])}
        budget = int(raw.get("max_tokens", default_budget))
        if budget <= 0:
            raise ValueError(f"task {raw.get('id', position)} max_tokens must be positive")

        index = build_index(repo, typescript_semantic=typescript_semantic)
        total_source_tokens = max(1, sum(max(1, record.size // 4) for record in index.records.values()))
        pack = build_context_pack(
            repo,
            query,
            max_tokens=budget,
            changed_boost=False,
            feedback_boost=False,
            index=index,
            adaptive_budget=adaptive_budget,
            typescript_semantic=typescript_semantic,
        )
        actual_symbols = {
            value.split(":", 1)[1].split("@", 1)[0]
            for value in pack.selected_symbols
            if ":" in value
        }
        results.append({
            "id": raw.get("id", position),
            "repo": str(repo),
            "file_recall": _recall(expected_files, set(pack.selected_files)),
            "symbol_recall": _recall(expected_symbols, actual_symbols),
            "tokens": pack.estimated_tokens,
            "token_reduction": 1.0 - min(1.0, pack.estimated_tokens / total_source_tokens),
            "selected_files": pack.selected_files,
            "missing_files": sorted(expected_files - set(pack.selected_files)),
            "missing_symbols": sorted(expected_symbols - actual_symbols),
        })

    return {
        "frozen": bool(frozen_at and declared_hash == computed_hash),
        "ground_truth_sha256": computed_hash,
        "tasks": results,
        "summary": {
            "task_count": len(results),
            "repository_count": len({item["repo"] for item in results}),
            "mean_file_recall": sum(item["file_recall"] for item in results) / len(results),
            "mean_symbol_recall": sum(item["symbol_recall"] for item in results) / len(results),
            "mean_token_reduction": sum(item["token_reduction"] for item in results) / len(results),
        },
    }

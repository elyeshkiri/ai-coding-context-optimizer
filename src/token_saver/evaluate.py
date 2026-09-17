"""Ground-truth evaluation for context selection quality."""

from __future__ import annotations

import json
from pathlib import Path

from .pack import build_context_pack
from .repo_index import build_index


def _recall(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 1.0


def evaluate_manifest(root: Path, manifest: Path, max_tokens: int = 6000) -> dict:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("manifest must contain a non-empty 'tasks' list")
    index = build_index(root)
    total_source_tokens = max(1, sum(max(1, record.size // 4) for record in index.records.values()))
    results = []
    for position, task in enumerate(tasks, start=1):
        query = str(task.get("query", ""))
        expected_files = set(task.get("files", []))
        expected_symbols = set(task.get("symbols", []))
        pack = build_context_pack(
            root, query, max_tokens=max_tokens, changed_boost=False,
            feedback_boost=False,
        )
        actual_symbols = {value.split(":", 1)[1].split("@", 1)[0] for value in pack.selected_symbols}
        results.append({
            "id": task.get("id", position),
            "file_recall": _recall(expected_files, set(pack.selected_files)),
            "symbol_recall": _recall(expected_symbols, actual_symbols),
            "tokens": pack.estimated_tokens,
            "token_reduction": 1.0 - min(1.0, pack.estimated_tokens / total_source_tokens),
        })
    return {
        "tasks": results,
        "summary": {
            "task_count": len(results),
            "mean_file_recall": sum(item["file_recall"] for item in results) / len(results),
            "mean_symbol_recall": sum(item["symbol_recall"] for item in results) / len(results),
            "mean_token_reduction": sum(item["token_reduction"] for item in results) / len(results),
        },
    }

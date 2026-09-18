"""Deterministic benchmark harness for the Output Saver compaction pass."""
from __future__ import annotations

import json
from pathlib import Path

from .output_saver import compact_output


def _load_text(case: dict, manifest: Path) -> str:
    has_text = isinstance(case.get("text"), str)
    has_path = isinstance(case.get("path"), str)
    if has_text == has_path:
        raise ValueError("each output benchmark case requires exactly one of text or path")
    if has_text:
        return case["text"]
    path = Path(case["path"]).expanduser()
    if not path.is_absolute():
        path = (manifest.parent / path).resolve()
    return path.read_text(encoding="utf-8")


def evaluate_output_manifest(manifest: Path) -> dict:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest must contain a non-empty 'cases' list")

    results: list[dict] = []
    seen: set[str] = set()
    for position, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"case {position} must be an object")
        case_id = str(case.get("id", position))
        if case_id in seen:
            raise ValueError(f"duplicate output benchmark id: {case_id}")
        seen.add(case_id)
        text = _load_text(case, manifest)
        mode = str(case.get("mode", "normal"))
        max_tokens = case.get("max_tokens")
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
                raise ValueError(f"case {case_id!r} max_tokens must be a positive integer")
        enforce = bool(case.get("enforce_budget", False))
        required = case.get("must_contain", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError(f"case {case_id!r} must_contain must be a list of strings")

        result = compact_output(
            text,
            mode=mode,
            max_tokens=max_tokens,
            enforce_budget=enforce,
        )
        missing_required = [item for item in required if item not in result.text]
        results.append({
            "id": case_id,
            "mode": result.mode,
            "budget_tokens": result.budget_tokens,
            "original_tokens": result.original_tokens,
            "output_tokens": result.output_tokens,
            "token_reduction": result.token_reduction,
            "removed_units": result.removed_units,
            "budget_exceeded": result.budget_exceeded,
            "code_preserved": result.code_preserved,
            "required_content_preserved": not missing_required,
            "missing_required": missing_required,
        })

    original = sum(item["original_tokens"] for item in results)
    output = sum(item["output_tokens"] for item in results)
    count = len(results)
    return {
        "cases": results,
        "summary": {
            "case_count": count,
            "original_tokens": original,
            "output_tokens": output,
            "weighted_token_reduction": 0.0 if original <= 0 else 1.0 - output / original,
            "mean_token_reduction": sum(item["token_reduction"] for item in results) / count,
            "code_preservation_rate": sum(item["code_preserved"] for item in results) / count,
            "required_content_preservation_rate": (
                sum(item["required_content_preserved"] for item in results) / count
            ),
            "budget_exceeded_rate": sum(item["budget_exceeded"] for item in results) / count,
        },
    }

"""Replay captured command output against preservation and savings contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .estimate import estimate_tokens
from .output_processors import process_output


def _case_text(case: dict, manifest: Path) -> str:
    """Return inline or file-backed fixture text for one quality case."""
    inline = isinstance(case.get("text"), str)
    from_file = isinstance(case.get("path"), str)
    if inline == from_file:
        raise ValueError("each quality case requires exactly one of text or path")
    if inline:
        return case["text"]
    path = Path(case["path"]).expanduser()
    if not path.is_absolute():
        path = (manifest.parent / path).resolve()
    return path.read_text(encoding="utf-8")


def quality_definition_hash(payload: dict) -> str:
    """Return the canonical SHA-256 of an output-quality case definition."""
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("quality manifest must contain a non-empty 'cases' list")
    canonical = json.dumps(
        cases,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _protocol(payload: dict, computed_hash: str) -> dict:
    """Return normalized freeze metadata for one output-quality manifest."""
    protocol = payload.get("protocol")
    declared_hash = (
        str(protocol.get("definition_sha256") or "").strip()
        if isinstance(protocol, dict)
        else ""
    )
    frozen_at = (
        protocol.get("frozen_at")
        if isinstance(protocol, dict)
        else None
    )
    frozen = bool(
        isinstance(protocol, dict) and protocol.get("frozen") is True
    )
    valid = bool(
        frozen
        and isinstance(frozen_at, str)
        and bool(frozen_at.strip())
        and declared_hash == computed_hash
    )
    return {
        "frozen": frozen,
        "frozen_at": frozen_at,
        "declared_definition_sha256": declared_hash or None,
        "computed_definition_sha256": computed_hash,
        "valid": valid,
    }


def evaluate_quality_manifest(
    manifest: Path,
    *,
    require_frozen: bool = False,
) -> dict:
    """Evaluate one output-quality manifest and optional freeze contract."""
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("quality manifest must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("quality manifest must contain a non-empty 'cases' list")

    computed_hash = quality_definition_hash(payload)
    protocol = _protocol(payload, computed_hash)
    if require_frozen and not protocol["valid"]:
        raise ValueError(
            "frozen output-quality manifest requires frozen=true, frozen_at, "
            "and matching definition_sha256; "
            f"computed={protocol['computed_definition_sha256']} "
            f"declared={protocol['declared_definition_sha256']}"
        )

    results: list[dict] = []
    seen: set[str] = set()
    for position, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"case {position} must be an object")
        case_id = str(case.get("id", position))
        if case_id in seen:
            raise ValueError(f"duplicate quality case id: {case_id}")
        seen.add(case_id)

        command = case.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"case {case_id!r} requires a non-empty command")
        exit_code = case.get("exit_code")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise ValueError(f"case {case_id!r} exit_code must be an integer")

        expected_processor = case.get("expected_processor")
        if expected_processor is not None and (
            not isinstance(expected_processor, str) or not expected_processor.strip()
        ):
            raise ValueError(
                f"case {case_id!r} expected_processor must be a non-empty string"
            )

        required = case.get("must_preserve", [])
        if not isinstance(required, list) or not all(
            isinstance(item, str) and item for item in required
        ):
            raise ValueError(
                f"case {case_id!r} must_preserve must be a list of non-empty strings"
            )
        forbidden = case.get("must_not_contain", [])
        if not isinstance(forbidden, list) or not all(
            isinstance(item, str) and item for item in forbidden
        ):
            raise ValueError(
                f"case {case_id!r} must_not_contain must be a list of non-empty strings"
            )

        max_tokens = case.get("max_tokens")
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ValueError(
                f"case {case_id!r} max_tokens must be a positive integer"
            )

        min_reduction = case.get("min_reduction", 0.0)
        if (
            isinstance(min_reduction, bool)
            or not isinstance(min_reduction, (int, float))
            or not 0 <= float(min_reduction) <= 1
        ):
            raise ValueError(
                f"case {case_id!r} min_reduction must be between 0 and 1"
            )

        text = _case_text(case, manifest)
        result = process_output(
            text,
            command,
            exit_code=exit_code,
            min_reduction=0.0,
        )
        original_tokens = estimate_tokens(text)
        output_tokens = estimate_tokens(result.text)
        reduction = (
            0.0
            if original_tokens <= 0
            else 1.0 - output_tokens / original_tokens
        )
        missing = [value for value in required if value not in result.text]
        introduced = [
            value
            for value in forbidden
            if value not in text and value in result.text
        ]
        budget_ok = max_tokens is None or output_tokens <= max_tokens
        reduction_ok = reduction + 1e-12 >= float(min_reduction)
        processor_ok = (
            expected_processor is None or result.processor == expected_processor
        )
        passed = (
            not missing
            and not introduced
            and budget_ok
            and reduction_ok
            and processor_ok
        )

        results.append(
            {
                "id": case_id,
                "command": command,
                "processor": result.processor,
                "expected_processor": expected_processor,
                "processor_ok": processor_ok,
                "failure_detected": result.failed,
                "compressed": result.compressed,
                "original_tokens": original_tokens,
                "output_tokens": output_tokens,
                "token_reduction": reduction,
                "recovered_critical_lines": len(result.recovered_lines),
                "missing_required": missing,
                "introduced_forbidden": introduced,
                "preservation_ok": not missing,
                "no_hallucination": not introduced,
                "budget_ok": budget_ok,
                "reduction_ok": reduction_ok,
                "passed": passed,
            }
        )

    original = sum(item["original_tokens"] for item in results)
    output = sum(item["output_tokens"] for item in results)
    return {
        "protocol": protocol,
        "cases": results,
        "summary": {
            "case_count": len(results),
            "passed": sum(item["passed"] for item in results),
            "failed": sum(not item["passed"] for item in results),
            "original_tokens": original,
            "output_tokens": output,
            "weighted_token_reduction": (
                0.0 if original <= 0 else 1.0 - output / original
            ),
            "preservation_rate": (
                sum(item["preservation_ok"] for item in results) / len(results)
            ),
            "processor_match_rate": (
                sum(item["processor_ok"] for item in results) / len(results)
            ),
            "no_hallucination_rate": (
                sum(item["no_hallucination"] for item in results) / len(results)
            ),
        },
    }

"""Everyday provider-boundary cost controls.

These controls are deliberately conservative:
* exact duplicate history is removed only when the bytes are identical and the
  omitted payload is recoverable locally;
* automatic model switching is opt-in and may only use a lower-cost model when
  a quality-gated calibration artifact explicitly admits that exact task bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from .efficiency.store import append_event
from .estimate import estimate_tokens
from .model_routing import (
    DEFAULT_ALLOWED_MODELS,
    DEFAULT_ROUTING_CALIBRATION_FILE,
    load_routing_calibration,
    route_task,
)
from .provider_boundary import (
    ProviderRequestProfile,
    gemini_function_responses,
    iter_gemini_function_response_strings,
)
from .recovery import RecoveryStore

PROVIDER_MODEL_ROUTING_MODES = ("off", "observe", "calibrated")


@dataclass(frozen=True)
class HistoryDedupResult:
    """Summarize exact duplicate historical tool-result suppression."""

    segments: int = 0
    estimated_tokens_saved: int = 0
    recovery_handles: tuple[str, ...] = ()


def _tool_text_refs(
    body: dict,
    profile: ProviderRequestProfile,
) -> list[tuple[Any, Any, str]]:
    """Return mutable references to explicit historical tool-result strings."""
    refs: list[tuple[Any, Any, str]] = []

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    block_content = block.get("content")
                    if isinstance(block_content, str):
                        refs.append((block, "content", block_content))
                    elif isinstance(block_content, list):
                        for item in block_content:
                            if (
                                isinstance(item, dict)
                                and item.get("type") == "text"
                                and isinstance(item.get("text"), str)
                            ):
                                refs.append((item, "text", item["text"]))
            if message.get("role") == "tool" and isinstance(content, str):
                refs.append((message, "content", content))

    input_items = body.get("input")
    if isinstance(input_items, list):
        for item in input_items:
            if (
                isinstance(item, dict)
                and item.get("type") in {"function_call_output", "tool_result"}
                and isinstance(item.get("output"), str)
            ):
                refs.append((item, "output", item["output"]))

    if profile.provider == "gemini":
        for parent, key in gemini_function_responses(body):
            response = parent[key]
            if isinstance(response, str):
                refs.append((parent, key, response))
                continue
            if not isinstance(response, (dict, list)):
                continue
            for leaf_parent, leaf_key in iter_gemini_function_response_strings(response):
                value = leaf_parent[leaf_key]
                if isinstance(value, str):
                    refs.append((leaf_parent, leaf_key, value))
    return refs


def deduplicate_provider_history(
    body: dict,
    profile: ProviderRequestProfile,
    *,
    recovery: RecoveryStore,
    min_tokens: int,
    enabled: bool = True,
) -> HistoryDedupResult:
    """Collapse later exact copies of large historical tool results.

    The first copy is preserved. Later copies are replaced by a small pointer
    only when the original bytes are stored in the exact-recovery database.
    """
    if not enabled:
        return HistoryDedupResult()
    seen: dict[str, str | None] = {}
    handles: list[str] = []
    saved = 0
    segments = 0

    for parent, key, text in _tool_text_refs(body, profile):
        original_tokens = estimate_tokens(text)
        if original_tokens < min_tokens:
            continue
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        if digest not in seen:
            seen[digest] = None
            continue

        handle = seen[digest]
        if handle is None:
            handle = recovery.put(
                text,
                content_type="text/plain",
                metadata={
                    "transform": "provider-history-exact-dedup",
                    "provider": profile.provider,
                },
            )
            seen[digest] = handle
        marker = (
            "[acco exact duplicate tool result omitted: identical bytes appeared "
            f"earlier in this request; recover {handle}]"
        )
        replacement_tokens = estimate_tokens(marker)
        if replacement_tokens >= original_tokens:
            continue
        parent[key] = marker
        handles.append(handle)
        segments += 1
        saved += original_tokens - replacement_tokens

    return HistoryDedupResult(
        segments=segments,
        estimated_tokens_saved=saved,
        recovery_handles=tuple(dict.fromkeys(handles)),
    )


def apply_calibrated_provider_route(
    root: Path,
    body: dict,
    profile: ProviderRequestProfile,
    *,
    prompt: str,
    input_tokens: int,
    mode: str = "off",
    calibration_file: str = DEFAULT_ROUTING_CALIBRATION_FILE,
    min_savings: float = 0.05,
) -> dict:
    """Observe or apply a provider model route without heuristic downgrades.

    Calibrated mode mutates the request model only when the selected cheaper
    model came from an accepted quality-gated calibration bucket. Static policy
    recommendations remain observational.
    """
    normalized = str(mode or "off").strip().lower()
    if normalized not in PROVIDER_MODEL_ROUTING_MODES:
        raise ValueError(
            "provider model routing mode must be one of: "
            + ", ".join(PROVIDER_MODEL_ROUTING_MODES)
        )
    metadata = {
        "mode": normalized,
        "evaluated": False,
        "applied": False,
        "from_model": body.get("model") if isinstance(body.get("model"), str) else None,
        "to_model": None,
        "action": None,
        "calibration_applied": False,
        "projected_savings_fraction": None,
        "reason": None,
    }
    if normalized == "off":
        metadata["reason"] = "disabled"
        return metadata
    if profile.provider != "anthropic":
        metadata["reason"] = "routing_profiles_currently_cover_anthropic_models_only"
        return metadata

    current = body.get("model")
    if not isinstance(current, str) or current not in DEFAULT_ALLOWED_MODELS:
        metadata["reason"] = "current_model_has_no_exact_routing_profile"
        return metadata
    if not prompt.strip():
        metadata["reason"] = "no_current_user_prompt"
        return metadata

    path = Path(calibration_file)
    if not path.is_absolute():
        path = root / path
    try:
        calibration = load_routing_calibration(path)
        decision = route_task(
            prompt,
            input_tokens=max(1, int(input_tokens)),
            current_model=current,
            min_savings=min_savings,
            conservative=True,
            calibration=calibration,
        )
    except (OSError, ValueError) as exc:
        metadata["reason"] = f"routing_unavailable:{type(exc).__name__}"
        append_event(
            root,
            {
                "kind": "provider_model_route",
                "feature": "model_routing",
                "applied": False,
                "reason": metadata["reason"],
            },
        )
        return metadata

    metadata.update(
        evaluated=True,
        to_model=decision.selected_model,
        action=decision.action,
        calibration_applied=decision.calibration_applied,
        projected_savings_fraction=decision.projected_savings_fraction,
    )
    can_apply = (
        normalized == "calibrated"
        and decision.action == "route"
        and decision.calibration_applied
        and decision.selected_model is not None
        and decision.selected_model != current
    )
    if can_apply:
        body["model"] = decision.selected_model
        metadata["applied"] = True
        metadata["reason"] = "quality_gated_calibration"
    elif normalized == "calibrated" and decision.action == "route":
        metadata["reason"] = "static_route_not_auto_applied"
    else:
        metadata["reason"] = "observe_only" if normalized == "observe" else "keep"

    append_event(
        root,
        {
            "kind": "provider_model_route",
            "feature": "model_routing",
            "applied": bool(metadata["applied"]),
            "from_model": current,
            "to_model": decision.selected_model,
            "action": decision.action,
            "calibration_applied": decision.calibration_applied,
            "projected_savings_fraction": decision.projected_savings_fraction,
        },
    )
    return metadata

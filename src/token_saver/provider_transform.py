"""Provider-request transformation with recovery, schema, and prefix accounting."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .context_router import route_context
from .estimate import estimate_tokens
from .prefix_cache import PrefixPlan, observe_prefix, stable_prefix_fingerprint
from .recovery import RecoveryCapacityError, RecoveryStore
from .tool_schema import compress_tool_catalog


@dataclass(frozen=True)
class ProviderTransformResult:
    """Describe one local provider-request optimization pass."""

    body: dict
    changed: bool
    original_tokens: int
    output_tokens: int
    recovery_handles: tuple[str, ...]
    schema_recovery_handle: str | None
    prefix: PrefixPlan

    def metadata(self) -> dict:
        """Return request transformation metadata without request content."""
        return {
            "changed": self.changed,
            "original_tokens": self.original_tokens,
            "output_tokens": self.output_tokens,
            "token_reduction": (
                max(0.0, 1.0 - self.output_tokens / self.original_tokens)
                if self.original_tokens else 0.0
            ),
            "recovery_handles": list(self.recovery_handles),
            "schema_recovery_handle": self.schema_recovery_handle,
            "prefix": self.prefix.to_dict(),
        }


def _json_tokens(value: Any) -> int:
    """Estimate tokens in compact JSON serialization."""
    return estimate_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _latest_user_text(body: dict) -> str:
    """Extract bounded query text from the latest user request item."""
    candidates = body.get("messages")
    if not isinstance(candidates, list):
        candidates = body.get("input")
    if not isinstance(candidates, list):
        return ""
    for item in reversed(candidates):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content[:2000]
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            return " ".join(parts)[:2000]
    return ""


def _looks_browser_payload(text: str) -> bool:
    """Return whether captured tool text appears to be HTML/browser context."""
    return bool(
        re.search(r"<(?:html|body|div|table|form|button|a)\b", text, re.I)
        or re.search(r"(?m)^\s*(?:role=|button\s+\[|link\s+\[|textbox\s+\[)", text)
    )


def _compress_tool_text(
    text: str,
    *,
    query: str,
    recovery: RecoveryStore,
    min_tokens: int,
) -> tuple[str, str | None]:
    """Route one large tool-result string through recoverable context transforms."""
    if estimate_tokens(text) < min_tokens:
        return text, None
    result = route_context(
        text,
        query=query,
        recovery=recovery,
        command="provider-tool-result",
        max_lines=100,
        min_reduction=0.08,
    )
    return (
        result.text,
        result.recovery_handle if result.changed else None,
    )

def _transform_content_blocks(
    blocks: list,
    *,
    query: str,
    recovery: RecoveryStore,
    min_tokens: int,
    handles: list[str],
) -> list:
    """Transform Anthropic-style tool-result content blocks."""
    out = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            out.append(block)
            continue
        updated = dict(block)
        content = updated.get("content")
        if isinstance(content, str):
            transformed, handle = _compress_tool_text(
                content,
                query=query,
                recovery=recovery,
                min_tokens=min_tokens,
            )
            updated["content"] = transformed
            if handle:
                handles.append(handle)
        elif isinstance(content, list):
            new_content = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    transformed, handle = _compress_tool_text(
                        item["text"],
                        query=query,
                        recovery=recovery,
                        min_tokens=min_tokens,
                    )
                    item = dict(item)
                    item["text"] = transformed
                    if handle:
                        handles.append(handle)
                new_content.append(item)
            updated["content"] = new_content
        out.append(updated)
    return out


def transform_provider_request(
    root: Path,
    provider: str,
    body: dict,
    *,
    compress_schemas: bool = True,
    compress_tool_results: bool = True,
    tool_result_min_tokens: int = 800,
    recovery_capacity_bytes: int = 512 * 1024 * 1024,
    prefix_tracking: bool = True,
) -> ProviderTransformResult:
    """Optimize a provider JSON request while retaining exact transformed source."""
    if not isinstance(body, dict):
        raise ValueError("provider request body must be a JSON object")
    original_tokens = _json_tokens(body)
    transformed = deepcopy(body)
    recovery = RecoveryStore(root, capacity_bytes=recovery_capacity_bytes)
    handles: list[str] = []
    schema_handle = None

    try:
        if compress_schemas and isinstance(transformed.get("tools"), list):
            schema = compress_tool_catalog(
                transformed["tools"],
                recovery=recovery,
                min_reduction=0.02,
            )
            if schema.changed:
                transformed["tools"] = schema.value
                schema_handle = schema.recovery_handle

        if compress_tool_results:
            query = _latest_user_text(transformed)
            messages = transformed.get("messages")
            if isinstance(messages, list):
                new_messages = []
                for message in messages:
                    if not isinstance(message, dict):
                        new_messages.append(message)
                        continue
                    updated = dict(message)
                    content = updated.get("content")
                    if isinstance(content, list):
                        updated["content"] = _transform_content_blocks(
                            content,
                            query=query,
                            recovery=recovery,
                            min_tokens=tool_result_min_tokens,
                            handles=handles,
                        )
                    if updated.get("role") == "tool" and isinstance(content, str):
                        updated["content"], handle = _compress_tool_text(
                            content,
                            query=query,
                            recovery=recovery,
                            min_tokens=tool_result_min_tokens,
                        )
                        if handle:
                            handles.append(handle)
                    new_messages.append(updated)
                transformed["messages"] = new_messages

            input_items = transformed.get("input")
            if isinstance(input_items, list):
                new_input = []
                for item in input_items:
                    if (
                        isinstance(item, dict)
                        and item.get("type") in {"function_call_output", "tool_result"}
                        and isinstance(item.get("output"), str)
                    ):
                        item = dict(item)
                        item["output"], handle = _compress_tool_text(
                            item["output"],
                            query=query,
                            recovery=recovery,
                            min_tokens=tool_result_min_tokens,
                        )
                        if handle:
                            handles.append(handle)
                    new_input.append(item)
                transformed["input"] = new_input
    except RecoveryCapacityError:
        transformed = deepcopy(body)
        handles = []
        schema_handle = None

    output_tokens = _json_tokens(transformed)
    changed = transformed != body and output_tokens < original_tokens
    if not changed:
        transformed = deepcopy(body)
        handles = []
        schema_handle = None
        output_tokens = original_tokens

    if prefix_tracking:
        prefix = observe_prefix(root, provider, transformed)
    else:
        fingerprint, tokens, size, components = stable_prefix_fingerprint(
            transformed
        )
        prefix = PrefixPlan(
            fingerprint=fingerprint,
            stable_tokens=tokens,
            stable_bytes=size,
            components=components,
            previous_fingerprint=None,
            reused=False,
        )
    return ProviderTransformResult(
        body=transformed,
        changed=changed,
        original_tokens=original_tokens,
        output_tokens=output_tokens,
        recovery_handles=tuple(dict.fromkeys(handles)),
        schema_recovery_handle=schema_handle,
        prefix=prefix,
    )

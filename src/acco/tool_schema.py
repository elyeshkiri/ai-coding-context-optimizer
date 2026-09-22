"""Conservative MCP/tool-schema compression with exact recovery support."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .recovery import RecoveryCapacityError, RecoveryStore

_DROP_ANNOTATIONS = {"title", "examples", "example", "$comment", "$schema"}
_USER_KEY_MAPS = {
    "properties",
    "$defs",
    "definitions",
    "patternProperties",
    "dependentSchemas",
    "dependentRequired",
    "dependencies",
}
_CONSTRAINT = re.compile(
    r"(?i)\b(?:must|cannot|can't|required|required|exactly|at least|at most|"
    r"minimum|maximum|min|max|enum|format|absolute|relative|invalid|reject|"
    r"only|one of|mutually exclusive|iso\d*|rfc\d*)\b"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_SHORT_DESCRIPTION = 180
_LEAD_BYTES = 96


@dataclass(frozen=True)
class ToolSchemaCompression:
    """Describe one deterministic schema compression attempt."""

    value: Any
    changed: bool
    original_bytes: int
    compressed_bytes: int
    recovery_handle: str | None = None

    @property
    def reduction(self) -> float:
        """Return byte reduction fraction."""
        if self.original_bytes <= 0:
            return 0.0
        return max(0.0, 1.0 - self.compressed_bytes / self.original_bytes)


def _shorten_description(value: str) -> str:
    """Keep a selection lead plus every recognized constraint sentence."""
    text = " ".join(value.split())
    if len(text.encode()) <= _SHORT_DESCRIPTION:
        return text
    sentences = [item.strip() for item in _SENTENCE.split(text) if item.strip()]
    if not sentences:
        return text
    kept: list[str] = []
    lead_taken = False
    for sentence in sentences:
        if _CONSTRAINT.search(sentence):
            kept.append(sentence)
            continue
        if not lead_taken:
            encoded = sentence.encode()
            if len(encoded) > _LEAD_BYTES:
                encoded = encoded[:_LEAD_BYTES]
                while encoded:
                    try:
                        sentence = encoded.decode()
                        break
                    except UnicodeDecodeError:
                        encoded = encoded[:-1]
                sentence = sentence.rsplit(" ", 1)[0] or sentence
            kept.append(sentence)
            lead_taken = True
    return " ".join(kept) if kept else text


def _compress_schema(value: Any, *, user_keys: bool = False) -> Any:
    """Recursively remove annotations while preserving construction semantics."""
    if isinstance(value, list):
        return [_compress_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        if user_keys:
            out[key] = _compress_schema(item)
            continue
        if key in _DROP_ANNOTATIONS:
            continue
        if key == "description" and isinstance(item, str):
            out[key] = _shorten_description(item)
            continue
        if key in _USER_KEY_MAPS:
            out[key] = _compress_schema(item, user_keys=True)
            continue
        out[key] = _compress_schema(item)
    return out


def _compress_tool(value: Any) -> Any:
    """Compress one MCP/OpenAI-style tool envelope without renaming fields."""
    if not isinstance(value, dict):
        return _compress_schema(value)
    out = dict(value)
    if isinstance(out.get("description"), str):
        out["description"] = _shorten_description(out["description"])
    for key in ("inputSchema", "input_schema", "parameters", "schema"):
        if key in out:
            out[key] = _compress_schema(out[key])
    return out


def compress_tool_catalog(
    catalog: list[dict] | dict,
    *,
    recovery: RecoveryStore | None = None,
    min_reduction: float = 0.02,
) -> ToolSchemaCompression:
    """Compress tool definitions only when the result is materially smaller."""
    original = json.dumps(
        catalog,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode()
    if isinstance(catalog, list):
        candidate: Any = [_compress_tool(item) for item in catalog]
    elif isinstance(catalog, dict) and isinstance(catalog.get("tools"), list):
        candidate = dict(catalog)
        candidate["tools"] = [_compress_tool(item) for item in catalog["tools"]]
    else:
        candidate = _compress_schema(catalog)
    compressed = json.dumps(
        candidate,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode()
    reduction = 1.0 - len(compressed) / len(original) if original else 0.0
    if len(compressed) >= len(original) or reduction < max(0.0, min_reduction):
        return ToolSchemaCompression(
            catalog,
            False,
            len(original),
            len(original),
            None,
        )
    handle = None
    if recovery is not None:
        try:
            handle = recovery.put(
                original,
                content_type="application/vnd.acco.tool-catalog+json",
                metadata={
                    "transform": "tool-schema-compression",
                    "compressed_bytes": len(compressed),
                },
            )
        except RecoveryCapacityError:
            return ToolSchemaCompression(
                catalog,
                False,
                len(original),
                len(original),
                None,
            )
    return ToolSchemaCompression(
        candidate,
        True,
        len(original),
        len(compressed),
        handle,
    )

"""Provider-shape detection and retrieval-first historical context traversal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_PROVIDERS = ("auto", "generic", "anthropic", "openai", "gemini")


@dataclass(frozen=True)
class ProviderRequestProfile:
    """Describe one provider request without storing request content."""

    provider: str
    shape: str
    streaming: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe request profile."""
        return {
            "provider": self.provider,
            "shape": self.shape,
            "streaming": self.streaming,
        }


def detect_provider_request(
    provider: str,
    body: dict,
    *,
    path: str = "",
) -> ProviderRequestProfile:
    """Resolve provider and request shape from explicit config, path, and structure."""
    configured = str(provider or "auto").strip().lower()
    if configured not in SUPPORTED_PROVIDERS:
        raise ValueError(
            "provider must be one of: " + ", ".join(SUPPORTED_PROVIDERS)
        )
    lowered_path = path.lower()

    inferred = configured
    if configured in {"auto", "generic"}:
        if "/messages" in lowered_path or "anthropic-version" in lowered_path:
            inferred = "anthropic"
        elif (
            "/chat/completions" in lowered_path
            or "/responses" in lowered_path
            or "openai" in lowered_path
        ):
            inferred = "openai"
        elif (
            ":generatecontent" in lowered_path
            or ":streamgeneratecontent" in lowered_path
            or "/models/" in lowered_path and "generatecontent" in lowered_path
        ):
            inferred = "gemini"
        elif isinstance(body.get("contents"), list):
            inferred = "gemini"
        elif isinstance(body.get("messages"), list):
            inferred = (
                "anthropic"
                if "system" in body and isinstance(body.get("max_tokens"), int)
                else "openai"
            )
        elif "input" in body:
            inferred = "openai"
        else:
            inferred = "generic"

    if inferred == "anthropic":
        shape = "anthropic-messages"
    elif inferred == "openai":
        if "/chat/completions" in lowered_path or isinstance(body.get("messages"), list):
            shape = "openai-chat"
        elif "/responses" in lowered_path or "input" in body:
            shape = "openai-responses"
        else:
            shape = "openai-generic"
    elif inferred == "gemini":
        shape = "gemini-generate-content"
    else:
        shape = "generic-json"

    streaming = bool(body.get("stream"))
    if inferred == "gemini" and ":streamgeneratecontent" in lowered_path:
        streaming = True
    return ProviderRequestProfile(inferred, shape, streaming)


def latest_user_text(body: dict, profile: ProviderRequestProfile) -> str:
    """Extract bounded user focus text without treating it as transformable context."""
    if profile.provider == "gemini":
        contents = body.get("contents")
        if isinstance(contents, list):
            for item in reversed(contents):
                if not isinstance(item, dict) or item.get("role") not in {None, "user"}:
                    continue
                parts = item.get("parts")
                if not isinstance(parts, list):
                    continue
                text = " ".join(
                    str(part.get("text"))
                    for part in parts
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
                if text:
                    return text[:2000]
        return ""

    candidates = body.get("messages")
    if isinstance(candidates, list):
        for item in reversed(candidates):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content[:2000]
            if isinstance(content, list):
                parts = [
                    block.get("text")
                    for block in content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]
                if parts:
                    return " ".join(parts)[:2000]

    value = body.get("input")
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, list):
        for item in reversed(value):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content[:2000]
            if isinstance(content, list):
                parts = [
                    block.get("text")
                    for block in content
                    if isinstance(block, dict) and isinstance(block.get("text"), str)
                ]
                if parts:
                    return " ".join(parts)[:2000]
    return ""


def iter_gemini_function_response_strings(value: Any):
    """Yield mutable parent/key pairs for long string leaves in Gemini responses."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield value, key
            elif isinstance(item, (dict, list)):
                yield from iter_gemini_function_response_strings(item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                yield value, index
            elif isinstance(item, (dict, list)):
                yield from iter_gemini_function_response_strings(item)


def gemini_function_responses(body: dict):
    """Yield Gemini function-response payload objects from historical contents."""
    contents = body.get("contents")
    if not isinstance(contents, list):
        return
    for content in contents:
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            response = part.get("functionResponse")
            if isinstance(response, dict) and "response" in response:
                yield response, "response"

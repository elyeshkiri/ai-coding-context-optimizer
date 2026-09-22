"""Stable-prefix accounting for provider requests and cache-aware transforms."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .estimate import estimate_tokens
from .state import load, update


@dataclass(frozen=True)
class PrefixPlan:
    """Describe the stable provider-request prefix without mutating the request."""

    fingerprint: str
    stable_tokens: int
    stable_bytes: int
    components: tuple[str, ...]
    previous_fingerprint: str | None
    reused: bool

    def to_dict(self) -> dict:
        """Return JSON-safe prefix metadata."""
        return {
            "fingerprint": self.fingerprint,
            "stable_tokens": self.stable_tokens,
            "stable_bytes": self.stable_bytes,
            "components": list(self.components),
            "previous_fingerprint": self.previous_fingerprint,
            "reused": self.reused,
        }


def _stable_payload(body: dict) -> tuple[dict, tuple[str, ...]]:
    """Extract request fields expected to remain stable across neighboring turns."""
    stable: dict = {}
    components: list[str] = []
    for key in ("system", "instructions", "tools", "tool_choice"):
        if key in body:
            stable[key] = body[key]
            components.append(key)

    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        prefix = list(messages)
        if isinstance(prefix[-1], dict) and prefix[-1].get("role") == "user":
            prefix = prefix[:-1]
        if prefix:
            stable["messages"] = prefix
            components.append("messages[:-latest-user]")

    input_items = body.get("input")
    if isinstance(input_items, list) and input_items:
        prefix = list(input_items)
        if isinstance(prefix[-1], dict) and prefix[-1].get("role") == "user":
            prefix = prefix[:-1]
        if prefix:
            stable["input"] = prefix
            components.append("input[:-latest-user]")
    return stable, tuple(components)


def stable_prefix_fingerprint(body: dict) -> tuple[str, int, int, tuple[str, ...]]:
    """Hash a canonical representation of the stable request prefix."""
    stable, components = _stable_payload(body)
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return digest, estimate_tokens(encoded.decode(errors="replace")), len(encoded), components


def observe_prefix(root: Path, provider: str, body: dict) -> PrefixPlan:
    """Record whether the transformed stable prefix matched the previous request."""
    fingerprint, tokens, size, components = stable_prefix_fingerprint(body)
    key = provider.strip().lower() or "generic"
    previous = load(root).get("prefix_cache", {}).get(key)
    previous_fingerprint = (
        str(previous.get("fingerprint"))
        if isinstance(previous, dict) and previous.get("fingerprint")
        else None
    )
    reused = previous_fingerprint == fingerprint

    def mutate(data: dict) -> None:
        cache = data.setdefault("prefix_cache", {})
        current = cache.get(key)
        if not isinstance(current, dict):
            current = {"hits": 0, "misses": 0}
        if previous_fingerprint is not None:
            bucket = "hits" if reused else "misses"
            current[bucket] = int(current.get(bucket, 0) or 0) + 1
        current.update(
            fingerprint=fingerprint,
            stable_tokens=tokens,
            stable_bytes=size,
            components=list(components),
        )
        cache[key] = current

    update(root, mutate)
    return PrefixPlan(
        fingerprint=fingerprint,
        stable_tokens=tokens,
        stable_bytes=size,
        components=components,
        previous_fingerprint=previous_fingerprint,
        reused=reused,
    )


def prefix_status(root: Path) -> dict:
    """Return prefix reuse counters without exposing request content."""
    raw = load(root).get("prefix_cache", {})
    if not isinstance(raw, dict):
        raw = {}
    providers: dict[str, dict] = {}
    for provider, value in sorted(raw.items()):
        if not isinstance(value, dict):
            continue
        hits = int(value.get("hits", 0) or 0)
        misses = int(value.get("misses", 0) or 0)
        attempts = hits + misses
        providers[str(provider)] = {
            "hits": hits,
            "misses": misses,
            "reuse_rate": hits / attempts if attempts else None,
            "stable_tokens": int(value.get("stable_tokens", 0) or 0),
            "stable_bytes": int(value.get("stable_bytes", 0) or 0),
            "components": list(value.get("components", [])),
            "fingerprint": value.get("fingerprint"),
        }
    return {"providers": providers}

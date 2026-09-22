"""Central registry of host capabilities relevant to Token Saver features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CapabilityLevel = Literal["yes", "no", "conditional", "advisory", "unknown"]


@dataclass(frozen=True)
class ClientCapabilities:
    """Describe what the installed Token Saver integration may rely on per host."""

    client: str
    capabilities: dict[str, CapabilityLevel]
    note: str = ""

    def level(self, name: str) -> CapabilityLevel:
        """Return the declared support level for one capability."""
        return self.capabilities.get(name, "unknown")

    def guaranteed(self, name: str) -> bool:
        """Return whether a capability is safe to assume without fallback."""
        return self.level(name) == "yes"

    def to_dict(self) -> dict:
        """Return a JSON-safe capability record."""
        return {
            "client": self.client,
            "capabilities": dict(sorted(self.capabilities.items())),
            "note": self.note,
        }


_BASE = {
    "pre_tool_intercept": "unknown",
    "post_tool_replace": "unknown",
    "prompt_ingress": "unknown",
    "session_hooks": "unknown",
    "mcp": "unknown",
    "dynamic_mcp_refresh": "unknown",
    "provider_base_url": "unknown",
    "model_route_execution": "unknown",
    "usage_observation": "unknown",
}


def _caps(client: str, note: str = "", **overrides: CapabilityLevel) -> ClientCapabilities:
    """Build one complete capability record from conservative defaults."""
    values = dict(_BASE)
    values.update(overrides)
    return ClientCapabilities(client=client, capabilities=values, note=note)


CLIENT_CAPABILITIES = {
    "claude-code": _caps(
        "claude-code",
        "Token Saver managed hooks cover pre/post tool, prompt, and session events.",
        pre_tool_intercept="yes",
        post_tool_replace="yes",
        prompt_ingress="yes",
        session_hooks="yes",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="yes",
    ),
    "codex": _caps(
        "codex",
        "Token Saver treats MCP/context integration as reliable and host hooks as conditional.",
        pre_tool_intercept="conditional",
        post_tool_replace="conditional",
        prompt_ingress="no",
        session_hooks="conditional",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="conditional",
    ),
    "cursor": _caps(
        "cursor",
        "MCP is the stable integration surface; editor-specific interception is not assumed.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="no",
        session_hooks="unknown",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "opencode": _caps(
        "opencode",
        "Project-local MCP is supported; Token Saver does not assume OpenCode-specific hook interception.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="no",
        session_hooks="unknown",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "openclaw": _caps(
        "openclaw",
        "Token Saver uses OpenClaw's native MCP registry; runtime propagation can depend on the selected OpenClaw agent runtime.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="unknown",
        session_hooks="unknown",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "hermes": _caps(
        "hermes",
        "Hermes discovers MCP tools from its user config; Token Saver does not assume Hermes-native hook parity.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="unknown",
        session_hooks="conditional",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "copilot": _caps(
        "copilot",
        "GitHub Copilot in VS Code consumes workspace MCP servers; editor hook interception is not assumed.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="no",
        session_hooks="unknown",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="unknown",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "antigravity": _caps(
        "antigravity",
        "Antigravity consumes workspace MCP profiles; Token Saver does not assume proprietary agent lifecycle hooks.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="unknown",
        session_hooks="unknown",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "gemini-cli": _caps(
        "gemini-cli",
        "Token Saver exposes reusable MCP/provider surfaces but does not assume vendor hook parity.",
        pre_tool_intercept="unknown",
        post_tool_replace="unknown",
        prompt_ingress="unknown",
        session_hooks="unknown",
        mcp="conditional",
        dynamic_mcp_refresh="conditional",
        provider_base_url="conditional",
        model_route_execution="advisory",
        usage_observation="unknown",
    ),
    "generic-mcp": _caps(
        "generic-mcp",
        "Only the MCP contract is assumed; every host-specific capability requires fallback.",
        mcp="yes",
        dynamic_mcp_refresh="conditional",
        model_route_execution="advisory",
    ),
}

FEATURE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "bash-output-rewrite": ("pre_tool_intercept", "post_tool_replace"),
    "smart-read-proxy": ("pre_tool_intercept", "post_tool_replace"),
    "prompt-ingress": ("prompt_ingress",),
    "continuity-hooks": ("session_hooks",),
    "adaptive-mcp": ("mcp", "dynamic_mcp_refresh"),
    "provider-proxy": ("provider_base_url",),
    "model-routing-execution": ("model_route_execution",),
    "usage-cost-observation": ("usage_observation",),
}


def normalize_client_name(value: str) -> str:
    """Normalize common host aliases to registry identifiers."""
    key = value.strip().lower().replace("_", "-")
    aliases = {
        "claude": "claude-code",
        "claudecode": "claude-code",
        "openai-codex": "codex",
        "open-code": "opencode",
        "open-claw": "openclaw",
        "hermes-agent": "hermes",
        "github-copilot": "copilot",
        "copilot-chat": "copilot",
        "google-antigravity": "antigravity",
        "gemini": "gemini-cli",
        "mcp": "generic-mcp",
        "generic": "generic-mcp",
    }
    return aliases.get(key, key)


def capabilities_for(client: str) -> ClientCapabilities:
    """Return a registered client capability record or a conservative unknown one."""
    key = normalize_client_name(client)
    return CLIENT_CAPABILITIES.get(
        key,
        _caps(key, "Unregistered client; Token Saver must use runtime detection/fallbacks."),
    )


def feature_support(client: str, feature: str) -> dict:
    """Explain whether one feature has guaranteed host prerequisites."""
    record = capabilities_for(client)
    required = FEATURE_REQUIREMENTS.get(feature)
    if required is None:
        raise KeyError(feature)
    levels = {name: record.level(name) for name in required}
    guaranteed = all(level == "yes" for level in levels.values())
    impossible = any(level == "no" for level in levels.values())
    return {
        "client": record.client,
        "feature": feature,
        "requirements": levels,
        "guaranteed": guaranteed,
        "available_with_fallback": not impossible,
    }


def capability_report(client: str | None = None) -> dict:
    """Return one client or the complete capability registry."""
    if client:
        record = capabilities_for(client)
        return {
            "client": record.to_dict(),
            "features": {
                feature: feature_support(record.client, feature)
                for feature in sorted(FEATURE_REQUIREMENTS)
            },
        }
    return {
        "clients": {
            name: record.to_dict()
            for name, record in sorted(CLIENT_CAPABILITIES.items())
        },
        "features": dict(sorted(FEATURE_REQUIREMENTS.items())),
    }

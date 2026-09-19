"""Disable MCP servers that never appear in session transcripts."""

from __future__ import annotations

from pathlib import Path

from .mcp import load_servers
from .sessions import Report


def used_server_names(report: Report) -> set[str]:
    """Handle used server names."""
    used: set[str] = set()
    for call in report.calls:
        name = call.name or ""
        if name.startswith("mcp__"):
            parts = name.split("__")
            if len(parts) >= 2 and parts[1]:
                used.add(parts[1])
        elif name.startswith("mcp-"):
            used.add(name.split("-", 1)[-1])
    return used


def classify_servers(root: Path, report: Report) -> tuple[list[str], set[str]]:
    """Classify servers."""
    declared = set(load_servers(root))
    used = used_server_names(report)
    return sorted(declared - used), used


def unused_servers(root: Path, report: Report) -> list[str]:
    """Handle unused servers."""
    unused, _used = classify_servers(root, report)
    return unused


def disable_unused(root: Path, names: list[str]) -> Path:
    """Disable unused."""
    path = root / ".claude" / "settings.json"
    from .config import update_json
    def mutate(current):
        existing = list(current.get("disabledMcpServers") or [])
        for name in names:
            if name not in existing: existing.append(name)
        current["disabledMcpServers"] = existing
        return current
    return update_json(path, mutate)

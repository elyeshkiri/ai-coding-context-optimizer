"""Fast one-line live efficiency status for coding-agent status bars."""

from __future__ import annotations

from pathlib import Path

from .efficiency.report import continuity_report, dashboard_report
from .prefix_cache import prefix_status


def live_status(root: Path, *, days: int = 1) -> dict:
    """Build a compact operational health snapshot from local ACCO telemetry."""
    report = dashboard_report(root, days=days)
    continuity = continuity_report(root)
    prefix = prefix_status(root)
    providers = prefix.get("providers", {})
    hits = sum(int(item.get("hits", 0)) for item in providers.values())
    misses = sum(int(item.get("misses", 0)) for item in providers.values())
    total = hits + misses
    reuse = hits / total if total else None
    waste = int(report["behavior"]["events"])
    tracked_files = len(continuity.get("working_files", []))
    health = "WATCH" if waste >= 5 else "HEALTHY"
    return {
        "schema": 1,
        "health": health,
        "estimated_saved_tokens": int(
            report["savings"]["estimated_tool_context_tokens"]
        ),
        "waste_signals": waste,
        "continuity_restores": int(report["continuity"]["restores"]),
        "working_files": tracked_files,
        "prefix_reuse_rate": reuse,
        "provider_calls": int(report["provider_usage"].get("calls", 0)),
        "window_days": days,
    }


def render_status(result: dict) -> str:
    """Render one terminal-friendly line without ANSI control sequences."""
    saved = int(result.get("estimated_saved_tokens", 0))
    if saved >= 1_000_000:
        saved_text = f"{saved / 1_000_000:.1f}M"
    elif saved >= 1_000:
        saved_text = f"{saved / 1_000:.1f}K"
    else:
        saved_text = str(saved)
    reuse = result.get("prefix_reuse_rate")
    reuse_text = "n/a" if reuse is None else f"{float(reuse):.0%}"
    return (
        f"ACCO | saved~{saved_text}t | waste {result.get('waste_signals', 0)} "
        f"| prefix {reuse_text} | files {result.get('working_files', 0)} "
        f"| {result.get('health', 'HEALTHY')}"
    )

"""Aggregate local session-efficiency evidence into a dashboard contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import time

from ..output_telemetry import output_telemetry_report
from .store import events_path, load_events, load_snapshot


def dashboard_report(root: Path, *, days: int = 7) -> dict:
    """Return a local savings and behavioral-efficiency report."""
    if days <= 0:
        raise ValueError("days must be positive")
    since = int(time.time()) - days * 86400
    events = load_events(root, since=since)
    savings = [
        event
        for event in events
        if event.get("kind") == "saving"
        and isinstance(event.get("estimated_tokens_saved"), int)
    ]
    by_feature: dict[str, int] = defaultdict(int)
    for event in savings:
        by_feature[str(event.get("feature") or "unknown")] += max(
            0, int(event["estimated_tokens_saved"])
        )
    waste = Counter(
        str(event.get("feature") or "unknown")
        for event in events
        if event.get("kind") == "waste"
    )
    continuity = sum(event.get("kind") == "continuity" for event in events)
    telemetry = output_telemetry_report(root)
    snapshot = load_snapshot(root)
    sessions = snapshot.get("sessions")
    return {
        "schema": 1,
        "root": str(root.resolve()),
        "window_days": days,
        "event_path": str(events_path(root)),
        "savings": {
            "estimated_tool_context_tokens": sum(by_feature.values()),
            "by_feature": dict(sorted(by_feature.items())),
            "events": len(savings),
            "trust": (
                "Estimated from observed before/after local tool text using the "
                "Token Saver estimator; not an API invoice."
            ),
        },
        "continuity": {
            "restores": continuity,
            "tracked_sessions": len(sessions) if isinstance(sessions, dict) else 0,
        },
        "behavior": {
            "signals": dict(sorted(waste.items())),
            "events": sum(waste.values()),
        },
        "billed_usage": telemetry["summary"],
        "evidence": {
            "billed_usage_source": "Claude transcript usage counters",
            "savings_source": "local observed tool transformations",
            "task_success": False,
            "quality_verified": False,
            "note": (
                "Use evidence-run/output-effectiveness for publishable cost-per-"
                "successful-task claims. The dashboard is operational telemetry."
            ),
        },
    }



def continuity_report(root: Path) -> dict:
    """Return the latest structured checkpoint without transcript content."""
    snapshot = load_snapshot(root)
    sessions = snapshot.get("sessions")
    last = snapshot.get("last_session")
    session = (
        sessions.get(last)
        if isinstance(sessions, dict) and isinstance(last, str)
        else None
    )
    if not isinstance(session, dict):
        session = {}
    return {
        "schema": 1,
        "root": str(root.resolve()),
        "available": bool(session),
        "task": session.get("task"),
        "working_files": list(session.get("working_files", [])),
        "commands": list(session.get("commands", [])),
        "failures": list(session.get("failures", [])),
        "validations": list(session.get("validations", [])),
        "last_activity": session.get("last_activity"),
        "privacy": (
            "No raw user prompt, assistant response, or tool output is stored "
            "in the continuity snapshot."
        ),
    }

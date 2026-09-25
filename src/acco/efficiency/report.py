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
    provider_events = [
        event for event in events if event.get("kind") == "provider_usage"
    ]
    provider_totals: dict[str, int] = defaultdict(int)
    provider_calls: Counter[str] = Counter()
    provider_models: Counter[str] = Counter()
    for event in provider_events:
        provider = str(event.get("provider") or "unknown")
        provider_calls[provider] += 1
        model = event.get("model")
        if isinstance(model, str) and model:
            provider_models[model] += 1
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "total_tokens",
        ):
            value = event.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                provider_totals[field] += value
    provider_route_events = [
        event for event in events if event.get("kind") == "provider_model_route"
    ]
    provider_route_applied = sum(
        event.get("applied") is True for event in provider_route_events
    )
    route_pairs = Counter(
        (
            str(event.get("from_model") or "unknown"),
            str(event.get("to_model") or "unknown"),
        )
        for event in provider_route_events
        if event.get("applied") is True
    )
    projected_route_savings = [
        float(event["projected_savings_fraction"])
        for event in provider_route_events
        if isinstance(event.get("projected_savings_fraction"), (int, float))
        and not isinstance(event.get("projected_savings_fraction"), bool)
    ]
    telemetry = output_telemetry_report(root, since=since)
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
                "ACCO estimator; not an API invoice."
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
        "provider_usage": {
            "calls": len(provider_events),
            **dict(provider_totals),
            "by_provider": dict(sorted(provider_calls.items())),
            "models": dict(sorted(provider_models.items())),
            "source": "provider-reported counters observed at the local boundary",
            "merged_with_billed_usage": False,
        },
        "model_routing": telemetry["routing"],
        "provider_model_routing": {
            "decisions": len(provider_route_events),
            "applied": provider_route_applied,
            "observed_only": max(
                0, len(provider_route_events) - provider_route_applied
            ),
            "applied_pairs": {
                f"{source}->{target}": count
                for (source, target), count in sorted(route_pairs.items())
            },
            "mean_projected_savings_fraction": (
                sum(projected_route_savings) / len(projected_route_savings)
                if projected_route_savings
                else None
            ),
            "projected_savings_samples": len(projected_route_savings),
            "trust": (
                "Routing projections use configured price/capability policy; "
                "applied routes require accepted quality-gated calibration."
            ),
        },
        "evidence": {
            "billed_usage_source": "Claude transcript usage counters",
            "provider_usage_source": (
                "separate provider-boundary response counters; never silently "
                "merged with transcript usage"
            ),
            "savings_source": "local observed tool/provider-context transformations",
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

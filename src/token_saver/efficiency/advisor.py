"""Measured local cost-intelligence and efficiency advice."""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
import time

from ..audit import audit
from ..output_telemetry import load_output_telemetry, output_telemetry_report
from ..pricing import load_rates
from .report import dashboard_report

_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_5m_input_tokens",
    "cache_creation_1h_input_tokens",
    "output_tokens",
    "model_calls",
)


def _num(value: object) -> int:
    """Return one finite nonnegative integer from local telemetry."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    value = float(value)
    return int(value) if math.isfinite(value) and value >= 0 else 0


def _records(root: Path, days: int) -> list[dict]:
    """Load project telemetry inside the requested window."""
    since = int(time.time()) - days * 86400
    return [
        item
        for item in load_output_telemetry(root)
        if isinstance(item.get("recorded_at"), int)
        and item["recorded_at"] >= since
    ]


def _single_model(record: dict) -> str | None:
    """Return the exact model id when one turn used exactly one model."""
    raw = record.get("models")
    if not isinstance(raw, list):
        return None
    models = sorted({str(model) for model in raw if str(model).strip()})
    return models[0] if len(models) == 1 else None


def _usage_by_model(records: list[dict]) -> dict:
    """Aggregate exact counters only for unambiguous single-model turns."""
    out: dict[str, dict[str, int]] = {}
    measured = 0
    mixed = 0
    for record in records:
        if not record.get("usage_available"):
            continue
        measured += 1
        model = _single_model(record)
        if model is None:
            mixed += 1
            continue
        bucket = out.setdefault(model, {"turns": 0, **dict.fromkeys(_FIELDS, 0)})
        bucket["turns"] += 1
        for field in _FIELDS:
            bucket[field] += _num(record.get(field))
    return {
        "models": dict(sorted(out.items())),
        "measured_turns": measured,
        "mixed_model_turns": mixed,
    }


def _turn_cost(record: dict, rates: dict) -> tuple[float | None, str | None]:
    """Price one measured turn or report why exact pricing is impossible."""
    model = _single_model(record)
    if model is None:
        return None, "turn contains zero or multiple model ids"
    rate = rates.get(model)
    if rate is None:
        return None, f"missing prices: {model}"
    created = _num(record.get("cache_creation_input_tokens"))
    five = _num(record.get("cache_creation_5m_input_tokens"))
    hour = _num(record.get("cache_creation_1h_input_tokens"))
    unknown = created - five - hour
    if unknown < 0:
        return None, "inconsistent cache TTL breakdown"
    if unknown and "cache_write_unknown" not in rate:
        return None, f"cache write TTL missing for {model}"
    total = (
        _num(record.get("input_tokens")) * rate["input"]
        + _num(record.get("cache_read_input_tokens")) * rate["cache_read"]
        + _num(record.get("output_tokens")) * rate["output"]
        + five * rate["cache_write_5m"]
        + hour * rate["cache_write_1h"]
        + unknown * rate.get("cache_write_unknown", 0)
    ) / 1_000_000
    return total, None


def _cost(records: list[dict], rates: dict | None) -> dict:
    """Return exact-priced coverage without extrapolating unpriced turns."""
    measured = [item for item in records if item.get("usage_available")]
    if rates is None:
        return {
            "available": False,
            "complete": False,
            "usd": None,
            "priced_usd": None,
            "priced_turns": 0,
            "measured_turns": len(measured),
            "coverage": 0.0,
            "incomplete_reasons": ["no explicit pricing file supplied"],
        }
    total = 0.0
    priced = 0
    reasons: Counter[str] = Counter()
    for record in measured:
        value, reason = _turn_cost(record, rates)
        if value is None:
            reasons[str(reason or "unpriced turn")] += 1
        else:
            total += value
            priced += 1
    complete = bool(measured) and priced == len(measured)
    return {
        "available": True,
        "complete": complete,
        "usd": total if complete else None,
        "priced_usd": total,
        "priced_turns": priced,
        "measured_turns": len(measured),
        "coverage": priced / len(measured) if measured else 0.0,
        "incomplete_reasons": [
            f"{reason} ({count} turn{'s' if count != 1 else ''})"
            for reason, count in sorted(reasons.items())
        ],
    }


def _category(name: str, ident: str, weight: int, score, evidence: dict, reason=None) -> dict:
    """Build one explicit score-category contract."""
    return {
        "id": ident,
        "name": name,
        "weight": weight,
        "available": score is not None,
        "score": score,
        "evidence": evidence,
        **({"reason": reason} if reason else {}),
    }


def _score(audit_tokens: int, usage: dict, dashboard: dict) -> dict:
    """Score transparent local diagnostics while preserving evidence coverage."""
    context_score = (
        30 if audit_tokens <= 1000
        else 26 if audit_tokens <= 2500
        else 20 if audit_tokens <= 5000
        else 12 if audit_tokens <= 10000
        else 5
    )
    categories = [
        _category(
            "Always-on context",
            "always_on_context",
            30,
            context_score,
            {"always_on_tokens": audit_tokens},
        )
    ]

    measured = _num(usage.get("measured_turns"))
    target = usage.get("target_met_rate")
    p90 = usage.get("p90_budget_utilization")
    if measured >= 5 and isinstance(target, (int, float)) and isinstance(p90, (int, float)):
        p90 = float(p90)
        fit = 4 if p90 <= .35 else 7 if p90 <= .60 else 10 if p90 <= .95 else 7 if p90 <= 1.10 else 3
        value = round(max(0.0, min(15.0, float(target) * 15.0)) + fit, 2)
        categories.append(_category(
            "Output budget fit",
            "output_budget",
            25,
            value,
            {"measured_turns": measured, "target_met_rate": float(target), "p90_budget_utilization": p90},
        ))
    else:
        categories.append(_category(
            "Output budget fit",
            "output_budget",
            25,
            None,
            {"measured_turns": measured},
            "requires at least 5 measured turns with output-budget evidence",
        ))

    fresh = _num(usage.get("input_tokens"))
    created = _num(usage.get("cache_creation_input_tokens"))
    read = _num(usage.get("cache_read_input_tokens"))
    total = fresh + created + read
    if measured >= 5 and total:
        ratio = read / total
        value = 25 if ratio >= .60 else 20 if ratio >= .40 else 15 if ratio >= .20 else 10 if ratio > 0 else 5
        categories.append(_category(
            "Cache reuse",
            "cache_reuse",
            25,
            value,
            {"cache_read_share": ratio, "fresh_input_tokens": fresh, "cache_creation_input_tokens": created, "cache_read_input_tokens": read},
        ))
    else:
        categories.append(_category(
            "Cache reuse",
            "cache_reuse",
            25,
            None,
            {"measured_turns": measured},
            "requires at least 5 measured turns with input usage counters",
        ))

    tracked = _num(dashboard.get("continuity", {}).get("tracked_sessions"))
    waste = _num(dashboard.get("behavior", {}).get("events"))
    if measured >= 5 and tracked:
        ratio = waste / measured
        value = 20 if waste == 0 else 18 if ratio <= .05 else 14 if ratio <= .15 else 9 if ratio <= .30 else 4
        categories.append(_category(
            "Behavioral waste control",
            "behavioral_waste",
            20,
            value,
            {"signals": waste, "signals_per_measured_turn": ratio, "tracked_sessions": tracked},
        ))
    else:
        categories.append(_category(
            "Behavioral waste control",
            "behavioral_waste",
            20,
            None,
            {"measured_turns": measured, "tracked_sessions": tracked},
            "requires at least 5 measured turns and tracked session state",
        ))

    available = [item for item in categories if item["available"]]
    maximum = sum(item["weight"] for item in available)
    points = sum(float(item["score"]) for item in available)
    percent = 100 * points / maximum if maximum else 0.0
    coverage = maximum / 100
    grade = None
    if coverage >= .5:
        grade = next(
            (label for floor, label in ((95, "A+"), (85, "A"), (70, "B"), (55, "C"), (40, "D")) if percent >= floor),
            "F",
        )
    return {
        "points": round(points, 2),
        "available_max_points": maximum,
        "percent": round(percent, 2),
        "coverage": coverage,
        "grade": grade,
        "categories": categories,
        "note": "Unavailable evidence is not silently scored as zero.",
    }


def _recommendations(audit_report, dashboard: dict, signals: dict, score: dict, cost: dict, rates_supplied: bool) -> list[dict]:
    """Return bounded next actions tied to measured or configured evidence."""
    items: list[dict] = []
    always_on = int(audit_report.always_on)
    if always_on > 5000:
        items.append(("high", "trim-always-on-context", f"{always_on:,} always-on tokens", "Move verbose/path-specific instructions out of always-on context; inspect with token-saver audit."))
    elif always_on > 2500:
        items.append(("medium", "review-always-on-context", f"{always_on:,} always-on tokens", "Review always-on imports and rules with token-saver audit."))

    if len(audit_report.mcp_servers) >= 4:
        items.append(("medium", "measure-mcp-overhead", f"{len(audit_report.mcp_servers)} MCP servers configured", "Measure/prune unused MCP schemas with token-saver mcp-prune; schema cost is not guessed."))

    underused = signals.get("underused_budget_groups", [])
    overruns = signals.get("frequent_target_overrun_groups", [])
    if underused:
        items.append(("medium", "lower-output-budgets", "Underused output budgets: " + ", ".join(underused[:5]), "Recalibrate with token-saver output-calibrate."))
    if overruns:
        items.append(("high", "fix-output-overruns", "Frequent target overruns: " + ", ".join(overruns[:5]), "Recalibrate output policy before lowering budgets."))

    cache = next((item for item in score["categories"] if item["id"] == "cache_reuse" and item["available"]), None)
    if cache and float(cache["evidence"]["cache_read_share"]) < .20:
        share = float(cache["evidence"]["cache_read_share"])
        items.append(("medium", "inspect-cache-stability", f"Cache-read share is {share:.1%}", "Inspect prompt/context churn; use token-saver cache-economics before rewriting stable prefixes."))

    waste = dashboard.get("behavior", {}).get("signals", {})
    actions = {
        "retry_loop": "Stop identical retries and revisit the failing hypothesis.",
        "repeated_command": "Reuse unchanged command evidence before rerunning.",
        "tool_cascade": "Consolidate findings before expanding another search cascade.",
    }
    if isinstance(waste, dict):
        for feature, action in actions.items():
            count = _num(waste.get(feature))
            if count:
                items.append(("high" if feature == "retry_loop" else "medium", "reduce-" + feature.replace("_", "-"), f"{feature.replace('_', ' ')}: {count} signal(s)", action))

    if not rates_supplied:
        items.append(("info", "supply-pricing", "No exact-model pricing file supplied", "Pass --rates FILE to price measured usage; Token Saver will not guess model prices."))
    elif not cost.get("complete") and cost.get("measured_turns"):
        items.append(("info", "complete-pricing-coverage", "; ".join(cost.get("incomplete_reasons", [])[:3]), "Add missing exact model/TTL rates instead of extrapolating."))

    order = {"high": 0, "medium": 1, "info": 2}
    return [
        {"priority": priority, "id": ident, "evidence": evidence, "action": action}
        for priority, ident, evidence, action in sorted(items, key=lambda row: (order[row[0]], row[1]))[:10]
    ]


def advisor_report(root: Path, *, days: int = 7, rates_path: str | Path | None = None, user_scope: bool = True) -> dict:
    """Build one measured local cost-intelligence report."""
    if days <= 0:
        raise ValueError("days must be positive")
    root = root.resolve()
    dashboard = dashboard_report(root, days=days)
    since = int(time.time()) - days * 86400
    telemetry = output_telemetry_report(root, since=since)
    audited = audit(root, user_scope=user_scope)
    records = _records(root, days)
    usage_models = _usage_by_model(records)
    rates = load_rates(rates_path) if rates_path is not None else None
    cost = _cost(records, rates)
    score = _score(audited.always_on, dashboard["billed_usage"], dashboard)
    saved = _num(dashboard.get("savings", {}).get("estimated_tool_context_tokens"))

    projection = {}
    if rates is not None and saved:
        for model in usage_models["models"]:
            if model in rates:
                projection[model] = saved * rates[model]["input"] / 1_000_000

    return {
        "schema": 1,
        "root": str(root),
        "window_days": days,
        "score": score,
        "context": {
            "always_on_tokens": audited.always_on,
            "on_demand_tokens": audited.on_demand,
            "counter": audited.counter_label,
            "mcp_servers_configured": list(audited.mcp_servers),
            "largest_always_on": [
                {"path": item.path, "kind": item.kind, "tokens": item.tokens, "note": item.note}
                for item in sorted(
                    (entry for entry in audited.items if entry.always_on),
                    key=lambda item: (-item.tokens, item.path),
                )[:8]
            ],
        },
        "usage": {"summary": dashboard["billed_usage"], **usage_models},
        "cost": cost,
        "savings": {
            **dashboard["savings"],
            "fresh_input_once_projection": {
                "available": bool(projection),
                "by_observed_model_usd": projection,
                "assumption": (
                    "Counterfactual only: each estimated saved tool-context token "
                    "is billed once as fresh input; cache/history effects excluded."
                    if projection else None
                ),
            },
        },
        "behavior": dashboard["behavior"],
        "continuity": dashboard["continuity"],
        "recommendations": _recommendations(
            audited, dashboard, telemetry.get("signals", {}), score, cost, rates is not None
        ),
        "evidence": {
            "measured": [
                "always-on context tokens",
                "Claude transcript usage/cache counters",
                "exact model ids on single-model turns",
                "waste and continuity events",
            ],
            "estimated": ["tool-context tokens saved from observed before/after text"],
            "projected": ["fresh-input-once scenario from explicit rates"] if projection else [],
            "not_claimed": [
                "task success",
                "quality preservation from operational telemetry",
                "end-to-end cost-per-success",
                "actual dollar savings from estimated tool-context tokens",
            ],
            "privacy": "No prompt text, assistant response text, or tool output is persisted by the advisor.",
        },
    }

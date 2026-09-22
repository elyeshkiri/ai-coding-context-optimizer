"""Validated Claude pricing registries and explicit rate loading."""

from __future__ import annotations

from datetime import date
from importlib.resources import files
import json
import math
from pathlib import Path

FIELDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
REGISTRY_SCHEMA = 1
_BUILTIN = "pricing_registry.json"


def _validate_rates(model: str, rates: object) -> dict[str, float]:
    """Validate one exact model's USD-per-million token rates."""
    if not isinstance(rates, dict) or any(key not in rates for key in FIELDS):
        raise ValueError(f"missing rates for {model}: {FIELDS}")
    result: dict[str, float] = {}
    for key in (*FIELDS, "cache_write_unknown"):
        if key not in rates:
            continue
        value = rates[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"invalid {model}.{key}")
        result[key] = float(value)
    return result


def validate_registry(payload: object) -> dict:
    """Validate and normalize the centralized pricing-registry contract."""
    if not isinstance(payload, dict):
        raise ValueError("pricing registry must be an object")
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"pricing registry schema must be {REGISTRY_SCHEMA}")
    for key in (
        "provider",
        "currency",
        "unit",
        "verified_at",
        "source_url",
        "source_markdown_url",
        "scope",
    ):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"pricing registry requires non-empty {key}")
    if payload["currency"] != "USD" or payload["unit"] != "per_million_tokens":
        raise ValueError("pricing registry must use USD per_million_tokens")
    try:
        date.fromisoformat(payload["verified_at"])
    except ValueError as exc:
        raise ValueError("pricing registry verified_at must be YYYY-MM-DD") from exc
    max_age = payload.get("max_age_days")
    if (
        isinstance(max_age, bool)
        or not isinstance(max_age, int)
        or max_age <= 0
    ):
        raise ValueError("pricing registry max_age_days must be a positive integer")

    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("pricing registry requires a non-empty models object")

    normalized_models: dict[str, dict] = {}
    seen_ids: set[str] = set()
    for model, entry in sorted(models.items()):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("pricing registry model ids must be non-empty strings")
        if not isinstance(entry, dict):
            raise ValueError(f"pricing registry entry for {model} must be an object")
        display = entry.get("display_name")
        if not isinstance(display, str) or not display.strip():
            raise ValueError(f"pricing registry {model} requires display_name")
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            raise ValueError(f"pricing registry {model}.aliases must be strings")
        identifiers = [model, *aliases]
        duplicate = next((item for item in identifiers if item in seen_ids), None)
        if duplicate is not None:
            raise ValueError(f"duplicate pricing model identifier: {duplicate}")
        seen_ids.update(identifiers)
        normalized_models[model] = {
            "display_name": display,
            "aliases": list(aliases),
            "rates": _validate_rates(model, entry.get("rates")),
        }

    return {
        **payload,
        "models": normalized_models,
    }


def load_registry(path: str | Path) -> dict:
    """Load one registry JSON file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_registry(payload)


def builtin_registry() -> dict:
    """Load the packaged, source-attributed Claude pricing registry."""
    resource = files("token_saver").joinpath(_BUILTIN)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return validate_registry(payload)


def registry_rates(registry: dict) -> dict[str, dict[str, float]]:
    """Flatten canonical ids and explicit aliases into exact rate lookups."""
    registry = validate_registry(registry)
    rates: dict[str, dict[str, float]] = {}
    for model, entry in registry["models"].items():
        value = dict(entry["rates"])
        rates[model] = value
        for alias in entry["aliases"]:
            rates[alias] = dict(value)
    return rates


def builtin_rates(*, require_fresh: bool = False) -> dict[str, dict[str, float]]:
    """Return packaged rates, optionally refusing stale registry metadata."""
    registry = builtin_registry()
    if require_fresh:
        status = registry_status(registry)
        if not status["fresh"]:
            raise ValueError(
                "builtin pricing registry is stale: "
                f"verified {status['verified_at']}, age {status['age_days']} days, "
                f"limit {status['max_age_days']} days"
            )
    return registry_rates(registry)


def load_rates(path: str | Path):
    """Load a legacy flat rate file, a registry file, or fresh builtin rates."""
    if str(path) == "builtin":
        return builtin_rates(require_fresh=True)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("schema") == REGISTRY_SCHEMA:
        return registry_rates(validate_registry(data))
    if not isinstance(data, dict) or not data:
        raise ValueError(
            "rates must map exact model IDs to USD rates per million tokens"
        )
    return {
        model: _validate_rates(model, rates)
        for model, rates in data.items()
    }


def registry_status(
    registry: dict,
    *,
    today: date | None = None,
    max_age_days: int | None = None,
) -> dict:
    """Return deterministic freshness and coverage metadata for one registry."""
    registry = validate_registry(registry)
    current = today or date.today()
    verified = date.fromisoformat(registry["verified_at"])
    age = (current - verified).days
    if age < 0:
        raise ValueError("pricing registry verified_at cannot be in the future")
    limit = registry["max_age_days"] if max_age_days is None else max_age_days
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("max_age_days must be a positive integer")
    aliases = sum(len(item["aliases"]) for item in registry["models"].values())
    return {
        "schema": REGISTRY_SCHEMA,
        "provider": registry["provider"],
        "currency": registry["currency"],
        "unit": registry["unit"],
        "verified_at": registry["verified_at"],
        "age_days": age,
        "max_age_days": limit,
        "fresh": age <= limit,
        "model_count": len(registry["models"]),
        "alias_count": aliases,
        "source_url": registry["source_url"],
        "source_markdown_url": registry["source_markdown_url"],
        "scope": registry["scope"],
    }


def cost(report, rates):
    """Price recorded API turns without filling unknown model or TTL rates."""
    total = 0.0
    reasons = set()
    if not report.turns:
        reasons.add("no recorded API usage")
    for turn in report.turns:
        rate = rates.get(turn.model)
        if rate is None:
            reasons.add(f"missing prices: {turn.model}")
            continue
        unknown = turn.created - turn.cache_5m - turn.cache_1h
        if unknown < 0:
            reasons.add("inconsistent cache TTL breakdown")
            continue
        if unknown and "cache_write_unknown" not in rate:
            reasons.add(
                "cache write TTL missing; supply explicit cache_write_unknown rate"
            )
            continue
        total += (
            turn.input_tokens * rate["input"]
            + turn.read * rate["cache_read"]
            + turn.output_tokens * rate["output"]
            + turn.cache_5m * rate["cache_write_5m"]
            + turn.cache_1h * rate["cache_write_1h"]
            + unknown * rate.get("cache_write_unknown", 0)
        ) / 1_000_000
    return {
        "usd": None if reasons else total,
        "incomplete_reasons": sorted(reasons),
    }

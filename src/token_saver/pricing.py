"""Explicit model-specific USD rates per million tokens. No guessed prices."""
import json
import math
from pathlib import Path

FIELDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")

def load_rates(path):
    """Load rates."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("rates must map exact model IDs to USD rates per million tokens")
    for model, rates in data.items():
        if not isinstance(rates, dict) or any(k not in rates for k in FIELDS):
            raise ValueError(f"missing rates for {model}: {FIELDS}")
        for key in (*FIELDS, "cache_write_unknown"):
            if key in rates and (isinstance(rates[key], bool) or not isinstance(rates[key], (int, float))
                                 or not math.isfinite(rates[key]) or rates[key] < 0):
                raise ValueError(f"invalid {model}.{key}")
    return data

def cost(report, rates):
    """Handle cost."""
    total = 0.0
    reasons = set()
    if not report.turns: reasons.add("no recorded API usage")
    for turn in report.turns:
        rate = rates.get(turn.model)
        if rate is None:
            reasons.add(f"missing prices: {turn.model}"); continue
        unknown = turn.created - turn.cache_5m - turn.cache_1h
        if unknown < 0:
            reasons.add("inconsistent cache TTL breakdown"); continue
        if unknown and "cache_write_unknown" not in rate:
            reasons.add("cache write TTL missing; supply explicit cache_write_unknown rate"); continue
        total += (turn.input_tokens * rate["input"] + turn.read * rate["cache_read"]
                  + turn.output_tokens * rate["output"] + turn.cache_5m * rate["cache_write_5m"]
                  + turn.cache_1h * rate["cache_write_1h"]
                  + unknown * rate.get("cache_write_unknown", 0)) / 1_000_000
    return {"usd": None if reasons else total, "incomplete_reasons": sorted(reasons)}

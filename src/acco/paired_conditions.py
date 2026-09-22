"""Canonical condition names shared by paired experiment/evaluation surfaces."""

from __future__ import annotations

BASELINE_CONDITION = "baseline"
OPTIMIZED_CONDITION = "token-saver"
CONDITION_ALIASES = {
    BASELINE_CONDITION: BASELINE_CONDITION,
    OPTIMIZED_CONDITION: OPTIMIZED_CONDITION,
    "enabled": OPTIMIZED_CONDITION,
}


def normalize_condition(value: object) -> str | None:
    """Normalize a public paired-run condition or return None when unsupported."""
    if not isinstance(value, str):
        return None
    return CONDITION_ALIASES.get(value.strip().lower())

"""Provider-cache-aware economics for context rewrites.

The policy works in relative input-cost units rather than hard-coded dollars.
Callers can supply provider/model-specific cache write/read factors while keeping
the decision logic deterministic and testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class CacheEconomicsDecision:
    """Describe projected relative input cost before and after one rewrite."""

    accepted: bool
    original_cost: float
    replacement_cost: float
    relative_savings: float | None
    cached_prefix_tokens: int
    original_frontier_tokens: int
    replacement_frontier_tokens: int
    invalidates_cached_prefix: bool
    expected_reuses: int
    cache_write_factor: float
    cache_read_factor: float
    min_relative_savings: float

    def to_dict(self) -> dict:
        """Return a JSON-compatible economics report."""
        return asdict(self)


def _nonnegative_int(value: int, name: str) -> int:
    """Validate one integer token/reuse count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _positive_factor(value: float, name: str) -> float:
    """Validate one positive pricing factor."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return numeric


def _fraction(value: float, name: str) -> float:
    """Validate one fractional threshold in the inclusive 0..1 range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number between 0 and 1")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0 or numeric > 1:
        raise ValueError(f"{name} must be a number between 0 and 1")
    return numeric


def assess_context_rewrite(
    *,
    original_frontier_tokens: int,
    replacement_frontier_tokens: int,
    cached_prefix_tokens: int = 0,
    invalidates_cached_prefix: bool = False,
    expected_reuses: int = 1,
    cache_write_factor: float = 1.25,
    cache_read_factor: float = 0.10,
    min_relative_savings: float = 0.0,
) -> CacheEconomicsDecision:
    """Estimate whether replacing context lowers cache-aware lifetime input cost.

    cached_prefix_tokens models already-cached history. A frontier-only rewrite
    pays a cache read for that prefix plus a cache write for the new frontier.
    A rewrite that mutates cached history must recreate the entire prefix, which
    can make an apparently smaller context more expensive.

    Factors are relative to ordinary uncached input cost.
    """
    original_frontier_tokens = _nonnegative_int(
        original_frontier_tokens,
        "original_frontier_tokens",
    )
    replacement_frontier_tokens = _nonnegative_int(
        replacement_frontier_tokens,
        "replacement_frontier_tokens",
    )
    cached_prefix_tokens = _nonnegative_int(
        cached_prefix_tokens,
        "cached_prefix_tokens",
    )
    expected_reuses = _nonnegative_int(expected_reuses, "expected_reuses")
    cache_write_factor = _positive_factor(cache_write_factor, "cache_write_factor")
    cache_read_factor = _positive_factor(cache_read_factor, "cache_read_factor")
    min_relative_savings = _fraction(min_relative_savings, "min_relative_savings")

    original_cost = (
        cached_prefix_tokens * cache_read_factor
        + original_frontier_tokens * cache_write_factor
        + expected_reuses
        * (cached_prefix_tokens + original_frontier_tokens)
        * cache_read_factor
    )
    if invalidates_cached_prefix:
        replacement_cost = (
            (cached_prefix_tokens + replacement_frontier_tokens)
            * cache_write_factor
            + expected_reuses
            * (cached_prefix_tokens + replacement_frontier_tokens)
            * cache_read_factor
        )
    else:
        replacement_cost = (
            cached_prefix_tokens * cache_read_factor
            + replacement_frontier_tokens * cache_write_factor
            + expected_reuses
            * (cached_prefix_tokens + replacement_frontier_tokens)
            * cache_read_factor
        )

    relative_savings = (
        1.0 - replacement_cost / original_cost if original_cost > 0 else None
    )
    accepted = (
        replacement_cost < original_cost
        and relative_savings is not None
        and relative_savings >= min_relative_savings
    )
    return CacheEconomicsDecision(
        accepted=accepted,
        original_cost=original_cost,
        replacement_cost=replacement_cost,
        relative_savings=relative_savings,
        cached_prefix_tokens=cached_prefix_tokens,
        original_frontier_tokens=original_frontier_tokens,
        replacement_frontier_tokens=replacement_frontier_tokens,
        invalidates_cached_prefix=invalidates_cached_prefix,
        expected_reuses=expected_reuses,
        cache_write_factor=cache_write_factor,
        cache_read_factor=cache_read_factor,
        min_relative_savings=min_relative_savings,
    )

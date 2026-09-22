"""Tests for cache-aware context rewrite economics."""

from __future__ import annotations

import pytest

from acco.cache_economics import assess_context_rewrite


def test_frontier_only_smaller_rewrite_is_economic():
    """A smaller new frontier should stay cheaper across expected cache reuses."""
    decision = assess_context_rewrite(
        original_frontier_tokens=1200,
        replacement_frontier_tokens=200,
        cached_prefix_tokens=8000,
        invalidates_cached_prefix=False,
        expected_reuses=3,
    )

    assert decision.accepted is True
    assert decision.replacement_cost < decision.original_cost
    assert decision.relative_savings is not None
    assert decision.relative_savings > 0


def test_cached_prefix_invalidation_can_make_smaller_context_more_expensive():
    """Rewriting cached history should include the cost of recreating that prefix."""
    decision = assess_context_rewrite(
        original_frontier_tokens=1000,
        replacement_frontier_tokens=100,
        cached_prefix_tokens=10000,
        invalidates_cached_prefix=True,
        expected_reuses=1,
    )

    assert decision.accepted is False
    assert decision.replacement_cost > decision.original_cost


def test_large_frontier_reduction_can_outweigh_cache_recreation():
    """A sufficiently large frontier saving may still justify prefix recreation."""
    decision = assess_context_rewrite(
        original_frontier_tokens=12000,
        replacement_frontier_tokens=100,
        cached_prefix_tokens=4000,
        invalidates_cached_prefix=True,
        expected_reuses=2,
    )

    assert decision.accepted is True


def test_minimum_relative_savings_can_preserve_marginal_rewrite():
    """The policy should reject tiny wins below a configured savings floor."""
    decision = assess_context_rewrite(
        original_frontier_tokens=1000,
        replacement_frontier_tokens=950,
        expected_reuses=1,
        min_relative_savings=0.10,
    )

    assert decision.accepted is False
    assert 0 < decision.relative_savings < 0.10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_frontier_tokens", -1),
        ("replacement_frontier_tokens", -1),
        ("cached_prefix_tokens", -1),
        ("expected_reuses", -1),
    ],
)
def test_invalid_integer_inputs_fail_closed(field, value):
    """Malformed token/reuse counts must not produce an economics decision."""
    kwargs = {
        "original_frontier_tokens": 100,
        "replacement_frontier_tokens": 50,
        "cached_prefix_tokens": 0,
        "expected_reuses": 1,
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        assess_context_rewrite(**kwargs)

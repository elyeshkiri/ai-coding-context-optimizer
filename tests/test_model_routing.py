"""Tests for deterministic capability- and cost-aware model routing."""

from __future__ import annotations

import json

import pytest

from token_saver.model_routing import (
    automatic_model_route,
    route_task,
)
from token_saver.state import load as load_state


def test_simple_explanation_routes_to_cheapest_eligible_model():
    """Simple explanatory work should admit the economy profile."""
    decision = route_task(
        "What is Redis and why is it useful?",
        input_tokens=1000,
        output_tokens=300,
    )

    assert decision.task == "explanation"
    assert decision.complexity_tier == "simple"
    assert decision.minimum_capability == "economy"
    assert decision.selected_model == "claude-haiku-4-5"
    assert decision.action == "recommend"
    assert decision.projected_cost_usd["claude-haiku-4-5"] < (
        decision.projected_cost_usd["claude-sonnet-5"]
    )


def test_debugging_never_downgrades_to_economy_profile():
    """Debugging requires at least the balanced routing profile."""
    decision = route_task(
        "Debug this failing request handler and explain the traceback.",
        input_tokens=1500,
        output_tokens=600,
    )

    assert decision.task == "debugging"
    assert decision.minimum_capability == "balanced"
    assert decision.selected_model == "claude-sonnet-5"
    assert "claude-haiku-4-5" not in decision.eligible_models


def test_high_risk_complex_change_escalates_to_deep_profile():
    """Complex high-risk coding should require the deep profile before pricing."""
    prompt = """
Implement a production authentication migration across multiple services.
- change the database schema and token storage
- update deployment and Kubernetes configuration
- migrate existing authorization state without data loss

The change must preserve backwards compatibility during rollout, handle
concurrent requests, include rollback behavior, update integration tests, and
cover security failure modes. Compare the old and new architecture, review
permission boundaries, validate the release pipeline, and provide a thorough
implementation plan before modifying the repository.
"""
    decision = route_task(prompt, input_tokens=5000, output_tokens=1500)

    assert decision.task == "coding"
    assert decision.risk_level == "high"
    assert decision.minimum_capability == "deep"
    assert decision.selected_model == "claude-opus-5"
    assert decision.eligible_models == ("claude-opus-5",)


def test_inadequate_allowed_models_return_manual_instead_of_unsafe_route():
    """An allow-list must never force a model below the capability policy."""
    decision = route_task(
        "Debug this production authentication race condition.",
        allowed_models=["claude-haiku-4-5"],
        input_tokens=1200,
        output_tokens=500,
    )

    assert decision.selected_model is None
    assert decision.action == "manual"
    assert decision.eligible_models == ()
    assert "no_allowed_model_satisfies_policy" in decision.reasons


def test_current_expensive_model_routes_only_when_savings_clear_threshold():
    """A suitable stronger model may switch only when configured savings justify it."""
    decision = route_task(
        "What is a JavaScript closure?",
        current_model="claude-sonnet-5",
        input_tokens=2000,
        output_tokens=400,
        min_savings=0.20,
    )

    assert decision.selected_model == "claude-haiku-4-5"
    assert decision.action == "route"
    assert decision.projected_savings_fraction is not None
    assert decision.projected_savings_fraction >= 0.20


def test_current_model_below_policy_routes_even_without_cost_savings_requirement():
    """Capability insufficiency should override the economic switching threshold."""
    decision = route_task(
        "Review this failing concurrency bug and identify the regression.",
        current_model="claude-haiku-4-5",
        input_tokens=1800,
        output_tokens=700,
        min_savings=1.0,
    )

    assert decision.selected_model == "claude-sonnet-5"
    assert decision.action == "route"
    assert "current_model_below_policy" in decision.reasons


def test_invalid_unknown_profile_is_rejected():
    """Unknown model ids require an explicit capability profile before routing."""
    with pytest.raises(ValueError, match="no routing capability profile"):
        route_task(
            "Explain this function",
            allowed_models=["claude-future-unknown"],
        )


def test_automatic_route_observe_mode_records_without_injecting(tmp_path, monkeypatch):
    """Observe mode should store content-free routing metadata only."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))

    note = automatic_model_route(
        tmp_path,
        "What is Redis?",
        session_id="session",
        enabled=True,
        mode="observe",
    )

    assert note is None
    state = load_state(tmp_path, "session")
    assert state["model_route"]["selected_model"] == "claude-haiku-4-5"
    assert state["model_route"]["task"] == "explanation"


def test_automatic_advisory_is_not_repeated_for_ambiguous_followup(
    tmp_path, monkeypatch
):
    """Unchanged route advice should not be injected on every continuation."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))

    first = automatic_model_route(
        tmp_path,
        "What is Redis?",
        session_id="session",
        enabled=True,
        mode="advisory",
    )
    second = automatic_model_route(
        tmp_path,
        "continue",
        session_id="session",
        enabled=True,
        mode="advisory",
    )

    assert first is not None
    assert "claude-haiku-4-5" in first
    assert "cannot switch the active top-level model itself" in first
    assert second is None


def test_decision_json_contract_is_serializable():
    """Orchestrators should be able to consume the route without custom encoders."""
    payload = route_task("What is Redis?").to_dict()

    encoded = json.dumps(payload)
    assert "claude-haiku-4-5" in encoded
    assert payload["pricing_basis"] == "fresh_input_plus_output_one_turn"
    assert payload["input_token_basis"] == "local_prompt_text_estimate_only"

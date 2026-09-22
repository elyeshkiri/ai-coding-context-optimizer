"""Tests for measured cost intelligence and efficiency advice."""

from __future__ import annotations

import json

import pytest

from acco.command_handlers.efficiency import cost_advisor_main
from acco.efficiency.advisor import advisor_report
from acco.efficiency.service import start_session
from acco.efficiency.store import append_event
from acco.output_telemetry import telemetry_path


def _turn(model: str | None = "claude-sonnet-5") -> dict:
    """Build one complete content-free telemetry turn."""
    return {
        "schema": 1,
        "recorded_at": 2_000_000_000,
        "turn_status": "completed",
        "task": "coding",
        "mode": "normal",
        "selected_budget": 100,
        "usage_available": True,
        "input_tokens": 100,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_5m_input_tokens": 12,
        "cache_creation_1h_input_tokens": 8,
        "output_tokens": 50,
        "model_calls": 1,
        "models": [model] if model else [],
        "budget_utilization": 0.5,
        "target_met": True,
        "task_success": None,
        "quality_verified": False,
    }


def _write_turns(root, state, turns) -> None:
    """Persist project-scoped telemetry rows under a controlled state directory."""
    path = telemetry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in turns),
        encoding="utf-8",
    )


def _rates(tmp_path):
    """Write one exact-model pricing fixture."""
    path = tmp_path / "rates.json"
    path.write_text(
        json.dumps(
            {
                "claude-sonnet-5": {
                    "input": 2.0,
                    "cache_write_5m": 2.5,
                    "cache_write_1h": 4.0,
                    "cache_read": 0.2,
                    "output": 10.0,
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_advisor_prices_only_explicit_measured_usage(tmp_path, monkeypatch):
    """Exact transcript counters plus explicit rates should produce exact local cost."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 2_000_000_100)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "CLAUDE.md").write_text("# Project\nkeep changes focused\n", encoding="utf-8")
    start_session(root, session_id="s1", source="startup")
    _write_turns(root, tmp_path / "state", [_turn() for _ in range(5)])
    append_event(
        root,
        {
            "kind": "saving",
            "feature": "output_compression",
            "estimated_tokens_saved": 100,
        },
    )

    report = advisor_report(
        root,
        days=7,
        rates_path=_rates(tmp_path),
        user_scope=False,
    )

    assert report["cost"]["complete"] is True
    assert report["cost"]["priced_turns"] == 5
    assert report["cost"]["usd"] == pytest.approx(0.00384)
    assert report["usage"]["models"]["claude-sonnet-5"]["turns"] == 5
    assert report["savings"]["estimated_tool_context_tokens"] == 100
    projection = report["savings"]["fresh_input_once_projection"]
    assert projection["by_observed_model_usd"]["claude-sonnet-5"] == pytest.approx(
        0.0002
    )
    assert "Counterfactual" in projection["assumption"]
    assert report["evidence"]["not_claimed"][0] == "task success"


def test_cost_advisor_cli_can_use_fresh_builtin_registry(
    tmp_path, monkeypatch, capsys
):
    """The explicit builtin source should price matching measured model usage."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 1_789_992_100)
    root = tmp_path / "repo"
    root.mkdir()
    _write_turns(root, tmp_path / "state", [_turn() for _ in range(5)])

    assert cost_advisor_main(
        [str(root), "--project-only", "--rates", "builtin", "--json"]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["cost"]["complete"] is True
    assert payload["cost"]["priced_turns"] == 5
    assert payload["cost"]["usd"] == pytest.approx(0.00384)


def test_advisor_does_not_allocate_mixed_model_turns(tmp_path, monkeypatch):
    """A mixed-model turn must stay unpriced instead of guessing token allocation."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 2_000_000_100)
    root = tmp_path / "repo"
    root.mkdir()
    record = _turn()
    record["models"] = ["claude-sonnet-5", "claude-opus-5"]
    _write_turns(root, tmp_path / "state", [record])

    report = advisor_report(
        root,
        rates_path=_rates(tmp_path),
        user_scope=False,
    )

    assert report["usage"]["mixed_model_turns"] == 1
    assert report["cost"]["complete"] is False
    assert report["cost"]["priced_turns"] == 0
    assert any(
        "multiple model ids" in reason
        for reason in report["cost"]["incomplete_reasons"]
    )


def test_advisor_keeps_missing_pricing_explicit(tmp_path, monkeypatch):
    """No pricing file should preserve measured tokens without a dollar guess."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 2_000_000_100)
    root = tmp_path / "repo"
    root.mkdir()
    _write_turns(root, tmp_path / "state", [_turn()])

    report = advisor_report(root, user_scope=False)

    assert report["cost"]["available"] is False
    assert report["cost"]["usd"] is None
    assert report["cost"]["incomplete_reasons"] == [
        "no explicit pricing file supplied"
    ]
    assert any(
        item["id"] == "supply-pricing"
        for item in report["recommendations"]
    )


def test_advisor_score_exposes_evidence_coverage(tmp_path, monkeypatch):
    """Sparse telemetry must not masquerade as a fully evidenced A-grade report."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 2_000_000_100)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "CLAUDE.md").write_text("# Small\n", encoding="utf-8")

    report = advisor_report(root, user_scope=False)

    assert report["score"]["coverage"] == pytest.approx(0.30)
    assert report["score"]["grade"] is None
    unavailable = [
        item["id"] for item in report["score"]["categories"] if not item["available"]
    ]
    assert set(unavailable) == {"output_budget", "cache_reuse", "behavioral_waste"}


def test_cost_advisor_cli_emits_structured_json(tmp_path, monkeypatch, capsys):
    """The CLI should expose the stable report contract without requiring prices."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("time.time", lambda: 2_000_000_100)
    root = tmp_path / "repo"
    root.mkdir()

    assert cost_advisor_main([str(root), "--project-only", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 1
    assert payload["root"] == str(root.resolve())
    assert payload["cost"]["usd"] is None
    assert payload["evidence"]["privacy"].startswith("No prompt text")

"""Tests for the centralized pricing registry and source-drift contract."""

from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path

import pytest

from acco.command_handlers.pricing import pricing_main
from acco.pricing import (
    builtin_rates,
    builtin_registry,
    load_rates,
    registry_status,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_builtin_registry_has_verified_current_core_models():
    """Packaged rates should expose current first-party standard model economics."""
    registry = builtin_registry()
    status = registry_status(registry, today=date(2026, 9, 21))

    assert status["fresh"] is True
    assert status["verified_at"] == "2026-09-21"
    assert status["model_count"] == 5
    assert registry["models"]["claude-sonnet-5"]["rates"] == {
        "input": 2.0,
        "cache_write_5m": 2.5,
        "cache_write_1h": 4.0,
        "cache_read": 0.2,
        "output": 10.0,
    }
    assert registry["models"]["claude-fable-5-1"]["rates"]["cache_read"] == 0.25


def test_builtin_rates_include_only_explicit_aliases():
    """Alias resolution must be declared rather than inferred from model strings."""
    rates = builtin_rates()

    assert rates["claude-haiku-4-5"] == rates["claude-haiku-4-5-20251001"]
    assert "claude-sonnet-5-latest" not in rates


def test_registry_freshness_can_fail_closed():
    """Age checks should become stale deterministically after the configured limit."""
    status = registry_status(
        builtin_registry(),
        today=date(2026, 10, 22),
    )

    assert status["fresh"] is False
    assert status["age_days"] == 31
    assert status["max_age_days"] == 30


def test_load_rates_preserves_legacy_flat_files(tmp_path):
    """Historical benchmark rate files remain valid and reproducible."""
    path = tmp_path / "rates.json"
    path.write_text(
        json.dumps(
            {
                "model-a": {
                    "input": 1,
                    "cache_write_5m": 1.25,
                    "cache_write_1h": 2,
                    "cache_read": 0.1,
                    "output": 5,
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_rates(path)["model-a"]["output"] == 5.0


def test_registry_rejects_duplicate_alias_identity():
    """One API identifier must never resolve to two different prices."""
    payload = builtin_registry()
    payload["models"]["claude-opus-5"]["aliases"] = ["claude-sonnet-5"]

    with pytest.raises(ValueError, match="duplicate pricing model identifier"):
        validate_registry(payload)


def test_live_source_matcher_detects_changed_rate():
    """The scheduled checker should notice an official table-row price change."""
    path = ROOT / "scripts" / "check_pricing_registry.py"
    spec = importlib.util.spec_from_file_location("pricing_drift_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registry = {
        **builtin_registry(),
        "models": {
            "claude-sonnet-5": builtin_registry()["models"]["claude-sonnet-5"]
        },
    }
    matching = (
        "| Claude Sonnet 5 | $2 / MTok | $2.50 / MTok | $4 / MTok | "
        "$0.20 / MTok | $10 / MTok |"
    )
    drifted = matching.replace("$10 / MTok", "$11 / MTok")

    assert module._live_mismatches(registry, matching) == []
    assert module._live_mismatches(registry, drifted) == ["claude-sonnet-5"]


def test_pricing_cli_resolves_one_canonical_model(capsys):
    """Pricing CLI should expose freshness plus exact model rates as JSON."""
    assert pricing_main(["--model", "claude-sonnet-5", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"]["fresh"] is True
    assert list(payload["models"]) == ["claude-sonnet-5"]
    assert payload["models"]["claude-sonnet-5"]["rates"]["input"] == 2.0

"""Tests for the frozen knowledge-assisted read-avoidance holdout."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from token_saver.knowledge_holdout import validate_knowledge_holdout_definition
from token_saver.knowledge_holdout_docker import (
    _PHASE1_PREFIX,
    _knowledge_seed_count,
)

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "benchmarks" / "knowledge-efficiency-swebench-24.frozen.json"


def test_frozen_knowledge_holdout_definition_is_valid():
    """The checked-in 24-task definition should be sealed and arm-isolated."""
    payload = json.loads(FROZEN.read_text(encoding="utf-8"))

    result = validate_knowledge_holdout_definition(payload)

    assert result["valid"] is True
    assert result["frozen"] is True
    assert len(payload["tasks"]) == 24
    assert payload["design"]["trials_per_task"] == 3
    assert result["comparison"]["baseline"] == "knowledge-memory-control"


def test_profile_gate_rejects_unrelated_condition_difference():
    """Only the declared knowledge/cache switches may differ between arms."""
    payload = json.loads(FROZEN.read_text(encoding="utf-8"))
    changed = deepcopy(payload)
    changed["runner"]["condition_profiles"]["enabled"]["env"]["UNRELATED"] = "1"

    with pytest.raises(ValueError, match="non_knowledge_condition_env_diff"):
        validate_knowledge_holdout_definition(changed, require_frozen=False)


def test_phase1_contract_requires_explicit_verified_findings():
    """The benchmark should measure explicit memory, not hidden auto-harvesting."""
    assert "token-saver remember" in _PHASE1_PREFIX
    assert "VERIFIED project findings" in _PHASE1_PREFIX
    assert "Do not store guesses" in _PHASE1_PREFIX


def test_knowledge_seed_count_reads_isolated_state(tmp_path):
    """Runner exposure evidence should count verified non-superseded findings."""
    directory = tmp_path / "knowledge"
    directory.mkdir()
    (directory / "project.json").write_text(
        json.dumps(
            {
                "findings": [
                    {"confidence": "verified"},
                    {"confidence": "probable"},
                    {"confidence": "verified", "superseded_by": "new"},
                    {"confidence": "verified"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _knowledge_seed_count(tmp_path) == 2

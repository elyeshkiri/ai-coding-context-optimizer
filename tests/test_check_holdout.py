import json
from pathlib import Path

import pytest

from scripts.check_holdout import _floor_failures, _ratcheted_floor


def test_floor_failures_detects_regression_and_missing_metric():
    summary = {
        "mean_file_recall": 0.82,
        "mean_symbol_recall": 0.90,
    }
    floor = {
        "mean_file_recall": 0.833,
        "mean_symbol_recall": 0.833,
        "mean_symbol_recall_in_expected_files": 0.667,
    }

    failures = _floor_failures(summary, floor)

    assert "mean_file_recall: 0.820 < floor 0.833" in failures
    assert "mean_symbol_recall_in_expected_files: missing from evaluation summary" in failures
    assert not any(item.startswith("mean_symbol_recall:") for item in failures)


def test_ratcheted_floor_never_lowers_existing_threshold():
    summary = {
        "mean_file_recall": 0.80,
        "mean_symbol_recall": 0.90,
    }
    floor = {
        "mean_file_recall": 0.833,
        "mean_symbol_recall": 0.833,
    }

    with pytest.raises(ValueError, match="mean_file_recall"):
        _ratcheted_floor(summary, floor)


def test_ratcheted_floor_raises_only_improved_metrics():
    summary = {
        "mean_file_recall": 0.8333333333,
        "mean_symbol_recall": 0.91,
        "mean_symbol_recall_in_expected_files": 0.75,
    }
    floor = {
        "mean_file_recall": 0.833,
        "mean_symbol_recall": 0.833,
        "mean_symbol_recall_in_expected_files": 0.667,
    }

    assert _ratcheted_floor(summary, floor) == {
        "mean_file_recall": 0.833,
        "mean_symbol_recall": 0.91,
        "mean_symbol_recall_in_expected_files": 0.75,
    }


def test_frozen_holdout_floor_gates_scoped_symbol_recall():
    root = Path(__file__).resolve().parents[1]
    spec = json.loads(
        (root / "benchmarks" / "holdout-external.floor.json").read_text()
    )

    assert spec["floor"]["mean_symbol_recall_in_expected_files"] == 0.667
    assert spec["target"]["mean_symbol_recall_in_expected_files"] == 1.0

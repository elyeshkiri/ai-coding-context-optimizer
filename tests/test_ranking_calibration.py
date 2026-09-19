"""Tests for empirical ranking-regression gate calibration."""

from __future__ import annotations

import json

from token_saver.command_handlers.evaluation import ranking_calibrate_main
from token_saver.command_registry import DEFAULT_COMMAND_REGISTRY
from token_saver.ranking_calibration import (
    calibrate_ranking_history,
    load_ranking_history,
    render_ranking_calibration_markdown,
)


def _report(
    *,
    ground_truth: str = "hash-a",
    rank_delta: int | None = 0,
    missing: bool = False,
    stage_delta: float = 0.0,
) -> dict:
    """Build one compact ranking-diff report for calibration tests."""
    baseline_rank = 2
    candidate_rank = None if missing else baseline_rank + (rank_delta or 0)
    regression = missing or bool(rank_delta and rank_delta > 0)
    improvement = bool(rank_delta and rank_delta < 0)
    return {
        "schema_version": 1,
        "ground_truth_sha256": ground_truth,
        "summary": {
            "task_count": 1,
            "expected_files_compared": 1,
            "regressed_files": int(regression),
            "improved_files": int(improvement),
            "missing_in_candidate": int(missing),
            "regression_tasks": int(regression),
            "improvement_tasks": int(improvement),
            "max_rank_drop": rank_delta if regression and rank_delta else 0,
            "stage_delta_totals": (
                {"bm25": stage_delta} if stage_delta else {}
            ),
        },
        "tasks": [
            {
                "id": "rank-one",
                "repository": "default",
                "query": "refresh session token",
                "files": [
                    {
                        "path": "auth.py",
                        "baseline_rank": baseline_rank,
                        "candidate_rank": candidate_rank,
                        "rank_delta": None if missing else rank_delta,
                        "baseline_score": 20.0,
                        "candidate_score": None if missing else 20.0 + stage_delta,
                        "score_delta": None if missing else stage_delta,
                        "regression": regression,
                        "improvement": improvement,
                        "stage_changes": [
                            {
                                "stage": "bm25",
                                "baseline": 10.0,
                                "candidate": 10.0 + stage_delta,
                                "delta": stage_delta,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_calibration_reports_empirical_rank_drop_distribution():
    """Positive rank drops should be summarized without being labeled as noise."""
    reports = [
        _report(rank_delta=1, stage_delta=-1.0),
        _report(rank_delta=2, stage_delta=-2.0),
        _report(rank_delta=7, stage_delta=-3.0),
        _report(rank_delta=0, stage_delta=0.5),
    ]

    result = calibrate_ranking_history(
        reports,
        ground_truth_sha256="hash-a",
        min_reports=4,
    )
    calibration = result["calibration"]

    assert calibration["gate_readiness"]["ready"] is True
    assert calibration["positive_rank_drop_count"] == 3
    assert calibration["rank_drop_percentiles"] == {
        "p50": 2,
        "p90": 7,
        "p95": 7,
        "p99": 7,
        "max": 7,
    }
    assert calibration["historical_support"]["zero_rank_drop"] is False
    assert calibration["historical_support"]["no_disappearance"] is True
    assert calibration["stage_activity"][0]["stage"] == "bm25"
    assert calibration["stage_activity"][0]["reports_changed"] == 4


def test_calibration_requires_enough_reports_before_supporting_strict_gate():
    """Zero observed regressions are insufficient before the evidence minimum."""
    result = calibrate_ranking_history(
        [_report(), _report()],
        ground_truth_sha256="hash-a",
        min_reports=3,
    )
    calibration = result["calibration"]

    assert calibration["gate_readiness"] == {
        "ready": False,
        "minimum_reports": 3,
        "remaining_reports": 1,
    }
    assert calibration["historical_support"]["zero_rank_drop"] is False
    assert calibration["historical_support"]["no_disappearance"] is False


def test_calibration_can_support_zero_drop_after_clean_history():
    """A sufficiently large clean cohort can factually support a strict history."""
    result = calibrate_ranking_history(
        [_report(), _report(), _report()],
        ground_truth_sha256="hash-a",
        min_reports=3,
    )
    calibration = result["calibration"]

    assert calibration["gate_readiness"]["ready"] is True
    assert calibration["historical_support"] == {
        "zero_rank_drop": True,
        "no_disappearance": True,
    }


def test_calibration_tracks_disappearances_separately():
    """Expected-file disappearance should invalidate no-disappearance support."""
    result = calibrate_ranking_history(
        [_report(), _report(missing=True)],
        ground_truth_sha256="hash-a",
        min_reports=2,
    )
    calibration = result["calibration"]

    assert calibration["missing_files"] == 1
    assert calibration["reports_with_missing"] == 1
    assert calibration["historical_support"]["no_disappearance"] is False


def test_calibration_filters_current_ground_truth_cohort():
    """Old benchmark definitions must not influence the selected current cohort."""
    result = calibrate_ranking_history(
        [
            _report(ground_truth="old", rank_delta=9),
            _report(ground_truth="current"),
            _report(ground_truth="current"),
        ],
        ground_truth_sha256="current",
        min_reports=2,
    )

    assert result["available_cohorts"] == {"current": 2, "old": 1}
    assert result["calibration"]["ground_truth_sha256"] == "current"
    assert result["calibration"]["regressed_files"] == 0
    assert result["calibration"]["historical_support"]["zero_rank_drop"] is True


def test_calibration_missing_current_cohort_is_nonfatal():
    """A new benchmark hash should report collecting evidence instead of failing."""
    result = calibrate_ranking_history(
        [_report(ground_truth="old")],
        ground_truth_sha256="new",
        min_reports=20,
    )

    calibration = result["calibration"]
    assert calibration["report_count"] == 0
    assert calibration["gate_readiness"]["remaining_reports"] == 20
    assert calibration["historical_support"]["zero_rank_drop"] is False


def test_load_history_skips_non_diff_json_files(tmp_path):
    """History directories may contain metadata JSON that is not a ranking diff."""
    (tmp_path / "valid.json").write_text(
        json.dumps(_report()),
        encoding="utf-8",
    )
    (tmp_path / "snapshot.json").write_text(
        json.dumps({"schema_version": 1, "tasks": []}),
        encoding="utf-8",
    )
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    reports = load_ranking_history(tmp_path)

    assert len(reports) == 1
    assert reports[0]["ground_truth_sha256"] == "hash-a"


def test_calibration_markdown_is_descriptive_not_automatic_policy():
    """Markdown should show evidence/readiness and explicitly avoid auto-thresholds."""
    result = calibrate_ranking_history(
        [_report(), _report()],
        ground_truth_sha256="hash-a",
        min_reports=3,
    )

    markdown = render_ranking_calibration_markdown(result)

    assert "## Token Saver ranking gate calibration" in markdown
    assert "collecting evidence" in markdown
    assert "1 more reports needed" in markdown
    assert "does not classify observed regressions as noise" in markdown


def test_ranking_calibrate_command_is_registered_and_supports_json(tmp_path, capsys):
    """CLI should aggregate a history directory using the registered command."""
    assert "ranking-calibrate" in DEFAULT_COMMAND_REGISTRY.names()
    (tmp_path / "one.json").write_text(json.dumps(_report()), encoding="utf-8")

    result = ranking_calibrate_main(
        [
            str(tmp_path),
            "--ground-truth-sha",
            "hash-a",
            "--min-reports",
            "1",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["calibration"]["report_count"] == 1
    assert payload["calibration"]["gate_readiness"]["ready"] is True

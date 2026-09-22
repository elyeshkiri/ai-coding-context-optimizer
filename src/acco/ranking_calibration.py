"""Empirical calibration for ranking-regression merge gates."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _load_report(path: Path) -> dict[str, Any]:
    """Load and minimally validate one ranking-diff report."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ranking diff must be a JSON object: {path}")
    ground_truth = payload.get("ground_truth_sha256")
    summary = payload.get("summary")
    tasks = payload.get("tasks")
    if not isinstance(ground_truth, str) or not ground_truth:
        raise ValueError(f"ranking diff is missing ground_truth_sha256: {path}")
    if not isinstance(summary, dict) or not isinstance(tasks, list):
        raise ValueError(f"ranking diff is missing summary/tasks: {path}")
    return payload


def load_ranking_history(path: Path) -> list[dict]:
    """Load ranking-diff JSON reports from one file or directory."""
    path = path.resolve()
    if path.is_file():
        return [_load_report(path)]
    if not path.is_dir():
        raise ValueError(f"ranking history path does not exist: {path}")

    reports = []
    for candidate in sorted(path.rglob("*.json")):
        try:
            reports.append(_load_report(candidate))
        except ValueError:
            continue
    return reports


def _nearest_rank_percentile(values: list[int], quantile: float) -> int | None:
    """Return the nearest-rank empirical percentile for positive integers."""
    if not values:
        return None
    ordered = sorted(values)
    position = max(1, math.ceil(quantile * len(ordered)))
    return ordered[position - 1]


def _stage_activity(reports: list[dict]) -> list[dict]:
    """Aggregate net and absolute per-stage score movement across reports."""
    totals: dict[str, dict[str, float | int]] = {}
    for report in reports:
        seen: set[str] = set()
        for task in report.get("tasks", []):
            if not isinstance(task, dict):
                continue
            for item in task.get("files", []):
                if not isinstance(item, dict):
                    continue
                for change in item.get("stage_changes", []):
                    if not isinstance(change, dict):
                        continue
                    stage = change.get("stage")
                    if not isinstance(stage, str) or not stage:
                        continue
                    delta = float(change.get("delta", 0.0))
                    state = totals.setdefault(
                        stage,
                        {
                            "net_delta": 0.0,
                            "absolute_delta": 0.0,
                            "max_absolute_delta": 0.0,
                            "reports_changed": 0,
                        },
                    )
                    state["net_delta"] = float(state["net_delta"]) + delta
                    state["absolute_delta"] = (
                        float(state["absolute_delta"]) + abs(delta)
                    )
                    state["max_absolute_delta"] = max(
                        float(state["max_absolute_delta"]),
                        abs(delta),
                    )
                    if not math.isclose(delta, 0.0, abs_tol=1e-12):
                        seen.add(stage)
        for stage in seen:
            totals[stage]["reports_changed"] = (
                int(totals[stage]["reports_changed"]) + 1
            )

    return sorted(
        (
            {"stage": stage, **values}
            for stage, values in totals.items()
            if not math.isclose(
                float(values["absolute_delta"]),
                0.0,
                abs_tol=1e-12,
            )
        ),
        key=lambda item: (
            -float(item["absolute_delta"]),
            str(item["stage"]),
        ),
    )


def _cohort_calibration(
    reports: list[dict],
    *,
    ground_truth_sha256: str,
    min_reports: int,
) -> dict:
    """Summarize one frozen-ground-truth cohort without inferring noise."""
    rank_drops: list[int] = []
    expected_files = 0
    regressed_files = 0
    improved_files = 0
    missing_files = 0
    reports_with_regression = 0
    reports_with_missing = 0
    no_movement_reports = 0

    for report in reports:
        summary = report["summary"]
        expected_files += int(summary.get("expected_files_compared", 0))
        regressed_files += int(summary.get("regressed_files", 0))
        improved_files += int(summary.get("improved_files", 0))
        missing = int(summary.get("missing_in_candidate", 0))
        missing_files += missing
        report_regressions = int(summary.get("regressed_files", 0))
        if report_regressions:
            reports_with_regression += 1
        if missing:
            reports_with_missing += 1

        moved = False
        for task in report.get("tasks", []):
            if not isinstance(task, dict):
                continue
            for item in task.get("files", []):
                if not isinstance(item, dict):
                    continue
                rank_delta = item.get("rank_delta")
                if isinstance(rank_delta, int) and rank_delta != 0:
                    moved = True
                if isinstance(rank_delta, int) and rank_delta > 0:
                    rank_drops.append(rank_delta)
                if item.get("candidate_rank") is None and item.get(
                    "baseline_rank"
                ) is not None:
                    moved = True
        if not moved:
            no_movement_reports += 1

    ready = len(reports) >= min_reports
    return {
        "ground_truth_sha256": ground_truth_sha256,
        "report_count": len(reports),
        "expected_file_observations": expected_files,
        "reports_with_regression": reports_with_regression,
        "reports_with_missing": reports_with_missing,
        "no_movement_reports": no_movement_reports,
        "regressed_files": regressed_files,
        "improved_files": improved_files,
        "missing_files": missing_files,
        "positive_rank_drop_count": len(rank_drops),
        "rank_drop_percentiles": {
            "p50": _nearest_rank_percentile(rank_drops, 0.50),
            "p90": _nearest_rank_percentile(rank_drops, 0.90),
            "p95": _nearest_rank_percentile(rank_drops, 0.95),
            "p99": _nearest_rank_percentile(rank_drops, 0.99),
            "max": max(rank_drops, default=None),
        },
        "stage_activity": _stage_activity(reports),
        "gate_readiness": {
            "ready": ready,
            "minimum_reports": min_reports,
            "remaining_reports": max(0, min_reports - len(reports)),
        },
        "historical_support": {
            "zero_rank_drop": ready and regressed_files == 0,
            "no_disappearance": ready and missing_files == 0,
        },
    }


def calibrate_ranking_history(
    reports: list[dict],
    *,
    ground_truth_sha256: str | None = None,
    min_reports: int = 20,
) -> dict:
    """Group ranking diffs by frozen ground truth and summarize gate evidence."""
    if min_reports <= 0:
        raise ValueError("min_reports must be positive")

    cohorts: dict[str, list[dict]] = {}
    for report in reports:
        ground_truth = report.get("ground_truth_sha256")
        if not isinstance(ground_truth, str) or not ground_truth:
            raise ValueError("ranking diff is missing ground_truth_sha256")
        cohorts.setdefault(ground_truth, []).append(report)

    if ground_truth_sha256 is not None:
        selected = cohorts.get(ground_truth_sha256, [])
        calibration = _cohort_calibration(
            selected,
            ground_truth_sha256=ground_truth_sha256,
            min_reports=min_reports,
        )
        return {
            "selected_ground_truth_sha256": ground_truth_sha256,
            "available_cohorts": {
                key: len(value)
                for key, value in sorted(cohorts.items())
            },
            "calibration": calibration,
        }

    return {
        "selected_ground_truth_sha256": None,
        "available_cohorts": {
            key: len(value)
            for key, value in sorted(cohorts.items())
        },
        "cohorts": [
            _cohort_calibration(
                group,
                ground_truth_sha256=key,
                min_reports=min_reports,
            )
            for key, group in sorted(
                cohorts.items(),
                key=lambda pair: (-len(pair[1]), pair[0]),
            )
        ],
    }


def render_ranking_calibration_markdown(report: dict) -> str:
    """Render a compact GitHub summary for one selected calibration cohort."""
    calibration = report.get("calibration")
    if not isinstance(calibration, dict):
        cohorts = report.get("cohorts")
        if not isinstance(cohorts, list) or not cohorts:
            return (
                "## Token Saver ranking gate calibration\n\n"
                "No ranking-regression history is available yet.\n"
            )
        calibration = cohorts[0]

    readiness = calibration["gate_readiness"]
    support = calibration["historical_support"]
    percentiles = calibration["rank_drop_percentiles"]
    lines = [
        "## Token Saver ranking gate calibration",
        "",
        (
            f"Current frozen cohort: "
            f"`{calibration['ground_truth_sha256'][:12]}…`"
        ),
        "",
        (
            f"Observed **{calibration['report_count']} PR reports** / "
            f"**{calibration['expected_file_observations']} expected-file "
            "observations**."
        ),
        (
            f"Regressions: **{calibration['regressed_files']} files** across "
            f"**{calibration['reports_with_regression']} reports**; "
            f"disappearances: **{calibration['missing_files']}**."
        ),
        "",
        (
            "Gate readiness: **ready**"
            if readiness["ready"]
            else (
                "Gate readiness: **collecting evidence** — "
                f"{readiness['remaining_reports']} more reports needed "
                f"for the configured minimum of {readiness['minimum_reports']}."
            )
        ),
        "",
        "| Evidence check | Historical support |",
        "|---|---|",
        (
            "| Zero expected-file rank drop | "
            f"{'yes' if support['zero_rank_drop'] else 'no / not yet'} |"
        ),
        (
            "| No expected-file disappearance | "
            f"{'yes' if support['no_disappearance'] else 'no / not yet'} |"
        ),
        "",
        "**Observed positive rank-drop distribution**",
        "",
        (
            f"count={calibration['positive_rank_drop_count']}, "
            f"p50={percentiles['p50']}, p90={percentiles['p90']}, "
            f"p95={percentiles['p95']}, p99={percentiles['p99']}, "
            f"max={percentiles['max']}"
        ),
        "",
    ]

    activity = calibration.get("stage_activity", [])
    if activity:
        lines.extend(
            [
                "**Most active scoring stages across the cohort**",
                "",
                "| Stage | Reports changed | |Δ| total | Max |Δ| | Net Δ |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for item in activity[:8]:
            lines.append(
                f"| `{item['stage']}` | {item['reports_changed']} | "
                f"{float(item['absolute_delta']):.3f} | "
                f"{float(item['max_absolute_delta']):.3f} | "
                f"{float(item['net_delta']):+.3f} |"
            )
        lines.append("")

    lines.extend(
        [
            "_This report is descriptive. It does not classify observed "
            "regressions as noise or automatically choose a blocking threshold._",
            "",
        ]
    )
    return "\n".join(lines)

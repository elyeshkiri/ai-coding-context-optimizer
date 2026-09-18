import json

import pytest

from token_saver.cost_report import (
    Pricing, compare_cost_files, compare_paired_agent_file, load_runs,
)


def _write(path, runs):
    path.write_text(json.dumps({"runs": runs}), encoding="utf-8")


def test_cost_report_measures_cost_per_success_and_outcomes(tmp_path):
    baseline = tmp_path / "baseline.json"
    optimized = tmp_path / "optimized.json"
    _write(baseline, [
        {
            "task_id": "a", "success": True,
            "input_tokens": 10000, "output_tokens": 2000,
            "tool_calls": 4, "model_calls": 2,
            "latency_ms": 2000, "cost_usd": 1.0,
        },
        {
            "task_id": "b", "success": False,
            "input_tokens": 8000, "output_tokens": 1000,
            "tool_calls": 5, "model_calls": 3,
            "latency_ms": 2500, "cost_usd": 0.8,
        },
    ])
    _write(optimized, [
        {
            "task_id": "a", "success": True,
            "input_tokens": 4000, "output_tokens": 800,
            "tool_calls": 2, "model_calls": 1,
            "latency_ms": 1200, "cost_usd": 0.35,
        },
        {
            "task_id": "b", "success": True,
            "input_tokens": 5000, "output_tokens": 1000,
            "tool_calls": 3, "model_calls": 2,
            "latency_ms": 1500, "cost_usd": 0.45,
        },
    ])

    result = compare_cost_files(baseline, optimized)

    assert result["paired_task_count"] == 2
    assert result["baseline"]["success_rate"] == 0.5
    assert result["optimized"]["success_rate"] == 1.0
    assert result["baseline"]["cost_per_success_usd"] == pytest.approx(1.8)
    assert result["optimized"]["cost_per_success_usd"] == pytest.approx(0.4)
    assert result["delta"]["cost_reduction"] == pytest.approx(1 - 0.8 / 1.8)
    assert result["delta"]["cost_per_success_reduction"] == pytest.approx(1 - 0.4 / 1.8)
    assert result["outcomes"]["improved_tasks"] == ["b"]
    assert result["outcomes"]["regressed_tasks"] == []


def test_cost_report_can_derive_cost_from_token_pricing(tmp_path):
    path = tmp_path / "runs.json"
    _write(path, [{
        "task_id": "a",
        "success": True,
        "input_tokens": 1_000_000,
        "cached_input_tokens": 200_000,
        "output_tokens": 100_000,
    }])

    runs = load_runs(
        path,
        Pricing(
            input_per_million=10,
            output_per_million=30,
            cached_input_per_million=2,
        ),
    )

    assert runs[0].cost_usd == pytest.approx(11.4)


def test_cost_report_rejects_unpaired_tasks_by_default(tmp_path):
    baseline = tmp_path / "baseline.json"
    optimized = tmp_path / "optimized.json"
    _write(baseline, [{"task_id": "a", "success": True, "cost_usd": 0.0}])
    _write(optimized, [{"task_id": "b", "success": True, "cost_usd": 0.0}])

    with pytest.raises(ValueError, match="same task_ids"):
        compare_cost_files(baseline, optimized)


def test_cached_input_cannot_exceed_input_tokens(tmp_path):
    path = tmp_path / "runs.json"
    _write(path, [{
        "task_id": "a",
        "success": True,
        "input_tokens": 10,
        "cached_input_tokens": 11,
    }])
    with pytest.raises(ValueError, match="cannot exceed"):
        load_runs(path)



def test_cost_report_rejects_missing_cost_without_pricing(tmp_path):
    path = tmp_path / "runs.json"
    _write(path, [{
        "task_id": "a",
        "success": True,
        "input_tokens": 100,
        "output_tokens": 10,
    }])
    with pytest.raises(ValueError, match="no cost_usd and no token pricing"):
        load_runs(path)



def test_cost_report_accepts_agent_evaluate_paired_manifest(tmp_path):
    path = tmp_path / "agent-runs.json"
    path.write_text(json.dumps({
        "runs": [
            {
                "task": "auth", "condition": "baseline", "success": True,
                "input_tokens": 1200, "output_tokens": 300,
                "seconds": 2.5, "tool_calls": 4, "cost_usd": 0.90,
            },
            {
                "task": "auth", "condition": "token-saver", "success": True,
                "input_tokens": 500, "output_tokens": 150,
                "seconds": 1.4, "tool_calls": 2, "cost_usd": 0.35,
            },
            {
                "task": "cache", "condition": "baseline", "success": False,
                "input_tokens": 1000, "output_tokens": 250,
                "seconds": 2.0, "cost_usd": 0.70,
            },
            {
                "task": "cache", "condition": "token-saver", "success": True,
                "input_tokens": 600, "output_tokens": 180,
                "seconds": 1.5, "cost_usd": 0.40,
            },
        ]
    }), encoding="utf-8")

    result = compare_paired_agent_file(path)

    assert result["paired_task_count"] == 2
    assert result["baseline"]["success_rate"] == 0.5
    assert result["optimized"]["success_rate"] == 1.0
    assert result["outcomes"]["improved_tasks"] == ["cache"]
    assert result["optimized"]["mean_latency_ms"] == pytest.approx(1450)

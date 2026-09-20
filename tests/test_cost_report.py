import json

import pytest

from token_saver.cost_report import (
    Pricing, Run, compare_cost_files, compare_costs, compare_paired_agent_file, load_runs,
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


def _run(task_id, success, tokens, cost, trial=""):
    return Run(
        task_id=task_id, success=success, input_tokens=tokens, output_tokens=0,
        cached_input_tokens=0, tool_calls=0, model_calls=1, latency_ms=0.0,
        cost_usd=cost, trial=trial,
    )


def test_compare_costs_rejects_duplicate_task_ids_instead_of_keeping_the_last():
    # Regression: the dict-by-task_id index silently kept the last run, so
    # 3 baseline attempts (1/3 successes) were reported as 1/1 = 100%.
    baseline = [_run("a", False, 100, 1.0), _run("a", False, 100, 1.0), _run("a", True, 100, 1.0)]
    optimized = [_run("a", False, 50, 0.5)]

    with pytest.raises(ValueError, match="duplicate task_id 'a'.*trial"):
        compare_costs(baseline, optimized)
    with pytest.raises(ValueError, match="duplicate task_id 'a'"):
        compare_costs(optimized, baseline)


def test_repeated_trials_pair_on_task_and_trial_and_count_every_run():
    baseline = [
        _run("a", False, 100, 1.0, "1"), _run("a", False, 100, 1.0, "2"),
        _run("a", True, 100, 1.0, "3"),
    ]
    optimized = [
        _run("a", True, 50, 0.5, "1"), _run("a", True, 50, 0.5, "2"),
        _run("a", False, 50, 0.5, "3"),
    ]

    result = compare_costs(baseline, optimized)

    assert result["paired_task_count"] == 3
    assert result["unique_task_count"] == 1
    assert result["baseline"]["success_rate"] == pytest.approx(1 / 3)
    assert result["optimized"]["success_rate"] == pytest.approx(2 / 3)
    assert result["baseline"]["total_tokens"] == 300
    assert result["outcomes"]["improved_tasks"] == ["a#1", "a#2"]
    assert result["outcomes"]["regressed_tasks"] == ["a#3"]


def test_unpaired_trials_are_reported_by_label():
    baseline = [_run("a", True, 1, 0.1, "1"), _run("a", True, 1, 0.1, "2")]
    optimized = [_run("a", True, 1, 0.1, "1")]

    with pytest.raises(ValueError, match=r"missing optimized=\['a#2'\]"):
        compare_costs(baseline, optimized)


def test_loaders_accept_trials_but_still_reject_true_duplicates(tmp_path):
    ok = tmp_path / "ok.json"
    _write(ok, [
        {"task_id": "a", "trial": 1, "success": True, "cost_usd": 1.0},
        {"task_id": "a", "trial": 2, "success": False, "cost_usd": 1.0},
    ])
    assert [r.trial for r in load_runs(ok)] == ["1", "2"]

    dup = tmp_path / "dup.json"
    _write(dup, [
        {"task_id": "a", "trial": 1, "success": True, "cost_usd": 1.0},
        {"task_id": "a", "trial": "1", "success": True, "cost_usd": 1.0},
    ])
    with pytest.raises(ValueError, match="duplicate task_id 'a' trial '1'"):
        load_runs(dup)

    no_trial = tmp_path / "no_trial.json"
    _write(no_trial, [
        {"task_id": "a", "success": True, "cost_usd": 1.0},
        {"task_id": "a", "success": True, "cost_usd": 1.0},
    ])
    with pytest.raises(ValueError, match="distinct 'trial'"):
        load_runs(no_trial)


def test_paired_manifest_supports_repeated_trials(tmp_path):
    path = tmp_path / "agent-runs.json"
    runs = []
    for trial, (b_ok, o_ok) in enumerate([(False, True), (True, True)], start=1):
        runs.append({"task": "auth", "trial": trial, "condition": "baseline",
                     "success": b_ok, "cost_usd": 1.0, "input_tokens": 100})
        runs.append({"task": "auth", "trial": trial, "condition": "token-saver",
                     "success": o_ok, "cost_usd": 0.5, "input_tokens": 50})
    path.write_text(json.dumps({"runs": runs}), encoding="utf-8")

    result = compare_paired_agent_file(path)

    assert result["paired_task_count"] == 2
    assert result["unique_task_count"] == 1
    assert result["baseline"]["success_rate"] == 0.5


def test_confidence_interval_is_wide_for_noisy_savings_and_deterministic():
    # Two tasks: one large saving, one regression. The point estimate hides how
    # little two tasks can support; the interval must say so.
    baseline = [_run("a", True, 1000, 1.0), _run("b", True, 1000, 1.0), _run("c", True, 1000, 1.0)]
    optimized = [_run("a", True, 100, 0.1), _run("b", True, 1500, 1.5), _run("c", True, 900, 0.9)]

    first = compare_costs(baseline, optimized)
    second = compare_costs(baseline, optimized)

    interval = first["confidence"]["intervals"]["total_token_reduction"]
    point = first["delta"]["total_token_reduction"]
    assert interval == second["confidence"]["intervals"]["total_token_reduction"]
    assert interval[0] < point < interval[1]
    assert interval[1] - interval[0] > 0.3
    assert first["confidence"]["task_clusters"] == 3


def test_confidence_interval_needs_at_least_two_tasks():
    result = compare_costs([_run("a", True, 100, 1.0)], [_run("a", True, 50, 0.5)])

    assert result["confidence"]["intervals"]["total_token_reduction"] is None
    assert "at least 2 distinct tasks" in result["confidence"]["note"]


def test_confidence_interval_clusters_repeated_trials_by_task():
    # Ten trials of a single task are one cluster, not ten independent samples.
    baseline = [_run("a", True, 100, 1.0, str(n)) for n in range(10)]
    optimized = [_run("a", True, 50, 0.5, str(n)) for n in range(10)]

    result = compare_costs(baseline, optimized)

    assert result["confidence"]["task_clusters"] == 1
    assert result["confidence"]["intervals"]["total_token_reduction"] is None


def test_cost_report_cli_prints_confidence_interval(tmp_path, capsys):
    from token_saver.commands import cost_report_main

    baseline = tmp_path / "baseline.json"
    optimized = tmp_path / "optimized.json"
    _write(baseline, [
        {"task_id": t, "success": True, "input_tokens": 1000, "cost_usd": 1.0}
        for t in "abc"
    ])
    _write(optimized, [
        {"task_id": "a", "success": True, "input_tokens": 100, "cost_usd": 0.1},
        {"task_id": "b", "success": True, "input_tokens": 1500, "cost_usd": 1.5},
        {"task_id": "c", "success": True, "input_tokens": 900, "cost_usd": 0.9},
    ])

    assert cost_report_main([str(baseline), str(optimized)]) == 0

    out = capsys.readouterr().out
    assert "95% CI over 3 tasks" in out
    assert "tokens" in out.split("95% CI over 3 tasks", 1)[1]



def test_paired_cost_report_accepts_experiment_enabled_alias(tmp_path):
    """Raw experiment output should not need enabled -> token-saver rewriting."""
    path = tmp_path / "experiment-runs.json"
    path.write_text(
        json.dumps({
            "runs": [
                {
                    "task": "auth",
                    "trial": 1,
                    "condition": "baseline",
                    "success": True,
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "cost_usd": 1.0,
                },
                {
                    "task": "auth",
                    "trial": 1,
                    "condition": "enabled",
                    "success": True,
                    "input_tokens": 500,
                    "output_tokens": 50,
                    "cost_usd": 0.5,
                },
            ]
        }),
        encoding="utf-8",
    )

    result = compare_paired_agent_file(path)

    assert result["paired_task_count"] == 1
    assert result["optimized"]["total_cost_usd"] == pytest.approx(0.5)

from pathlib import Path

from acco.experiment import build_schedule, validate_suite


SUITE = Path(__file__).parents[1] / "benchmarks" / "e2e-swebench-24.frozen.json"


def test_frozen_swebench_suite_is_publishable_and_hash_valid():
    suite = validate_suite(SUITE, require_frozen=True, require_broad=True)

    assert len(suite["tasks"]) == 24
    assert len(suite["repositories"]) == 7
    assert suite["design"]["trials_per_task"] == 3
    assert suite["runner"]["model"] == "claude-sonnet-5"
    assert len(build_schedule(suite)) == 144
    assert all(task.get("swebench") for task in suite["tasks"])
    assert all(task.get("test_patch") for task in suite["tasks"])


def test_hidden_grader_material_is_not_in_agent_prompts():
    suite = validate_suite(SUITE, require_frozen=True, require_broad=True)

    for task in suite["tasks"]:
        assert task["test_patch"] not in task["prompt"]
        for test_id in task["source"]["fail_to_pass"]:
            assert test_id not in task["prompt"]

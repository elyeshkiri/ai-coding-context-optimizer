from token_saver.benchmark import _publishability_issues, task_definition_hash


def _manifest(task_count=20, trials=3):
    tasks = [
        {
            "id": f"task-{n}",
            "repository": "repo",
            "revision": "a" * 40,
            "prompt_sha256": f"{n:064x}"[-64:],
            "verifier": [["pytest", "-q", f"tests/test_{n}.py"]],
        }
        for n in range(task_count)
    ]
    manifest = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-19T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {
            "trials_per_task": trials,
            "condition_order_seed": 1729,
        },
        "tasks": tasks,
    }
    manifest["protocol"]["task_definition_sha256"] = task_definition_hash(manifest)
    runs = []
    for task in tasks:
        for trial in range(1, trials + 1):
            for condition in ("baseline", "enabled"):
                runs.append({
                    "task": task["id"],
                    "trial": trial,
                    "condition": condition,
                    "revision": task["revision"],
                    "model": "exact-model-id",
                    "prompt_sha256": task["prompt_sha256"],
                    "manual_intervention": False,
                })
    return manifest, runs


def test_publishability_gate_accepts_20_tasks_with_three_trials():
    manifest, runs = _manifest()
    assert _publishability_issues(manifest, runs) == []


def test_publishability_gate_rejects_small_or_unfrozen_evidence():
    manifest, runs = _manifest(task_count=19, trials=2)
    manifest["protocol"]["condition_order_randomized"] = False

    issues = _publishability_issues(manifest, runs)

    assert any("at least 20" in issue for issue in issues)
    assert any("at least 3" in issue for issue in issues)
    assert any("condition_order_randomized" in issue for issue in issues)


def test_task_definition_hash_changes_when_verifier_changes():
    manifest, _runs = _manifest()
    before = task_definition_hash(manifest)
    manifest["tasks"][0]["verifier"][0].append("--maxfail=1")
    after = task_definition_hash(manifest)

    assert before != after

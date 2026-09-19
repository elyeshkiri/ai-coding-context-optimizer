import json

from token_saver.output_quality import evaluate_quality_manifest


def _pytest_failure():
    chatter = "\n".join(f"collecting test_{i}" for i in range(200))
    return (
        chatter
        + "\n============================= FAILURES =============================\n"
        + "____________________________ test_refresh ____________________________\n"
        + "E   AssertionError: expected 200, got 401\n"
        + "=========================== short test summary info ===========================\n"
        + "FAILED tests/test_auth.py::test_refresh - AssertionError: expected 200, got 401\n"
        + "======================= 1 failed, 80 passed in 1.2s =======================\n"
    )


def test_quality_replay_checks_preservation_budget_and_reduction(tmp_path):
    manifest = tmp_path / "quality.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "pytest-auth",
            "command": "pytest -q",
            "exit_code": 1,
            "text": _pytest_failure(),
            "must_preserve": [
                "tests/test_auth.py::test_refresh",
                "AssertionError: expected 200, got 401",
            ],
            "max_tokens": 250,
            "min_reduction": 0.50,
        }]
    }), encoding="utf-8")

    report = evaluate_quality_manifest(manifest)
    case = report["cases"][0]
    assert case["processor"] == "pytest"
    assert case["passed"] is True
    assert case["preservation_ok"] is True
    assert case["token_reduction"] >= 0.50
    assert report["summary"]["failed"] == 0


def test_quality_replay_fails_when_required_diagnostic_is_missing(tmp_path):
    manifest = tmp_path / "quality.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "missing-contract",
            "command": "git log --oneline",
            "text": "\n".join(f"{i:04x} change {i}" for i in range(100)),
            "must_preserve": ["must-never-appear"],
        }]
    }), encoding="utf-8")

    report = evaluate_quality_manifest(manifest)
    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["missing_required"] == ["must-never-appear"]
    assert report["summary"]["failed"] == 1


def test_quality_replay_reads_capture_from_file(tmp_path):
    capture = tmp_path / "pytest.txt"
    capture.write_text(_pytest_failure(), encoding="utf-8")
    manifest = tmp_path / "quality.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "file",
            "command": "pytest",
            "exit_code": 1,
            "path": "pytest.txt",
            "must_preserve": ["test_refresh"],
        }]
    }), encoding="utf-8")

    assert evaluate_quality_manifest(manifest)["cases"][0]["passed"] is True

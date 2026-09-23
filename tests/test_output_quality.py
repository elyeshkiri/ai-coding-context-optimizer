import json

from acco.output.contracts import OutputResult
from acco.output_quality import (
    evaluate_quality_manifest,
    quality_definition_hash,
)


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



def test_frozen_quality_manifest_recomputes_definition_hash(tmp_path):
    """Frozen output fixtures should be rejected after any case mutation."""
    manifest = tmp_path / "quality.json"
    payload = {
        "protocol": {
            "frozen": True,
            "frozen_at": "2026-09-20T13:00:00Z",
            "definition_sha256": "",
        },
        "cases": [
            {
                "id": "git-log",
                "command": "git log --oneline",
                "text": "\n".join(
                    f"{index:04x} change {index}" for index in range(80)
                ),
                "must_preserve": ["change 0"],
                "min_reduction": 0.1,
            }
        ],
    }
    payload["protocol"]["definition_sha256"] = quality_definition_hash(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_quality_manifest(manifest, require_frozen=True)
    assert result["protocol"]["valid"] is True

    payload["cases"][0]["must_preserve"].append("change 79")
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    try:
        evaluate_quality_manifest(manifest, require_frozen=True)
    except ValueError as exc:
        assert "matching definition_sha256" in str(exc)
    else:
        raise AssertionError("mutated frozen fixture must be rejected")


def test_quality_replay_rejects_introduced_forbidden_text(tmp_path, monkeypatch):
    """A smaller output that invents a diagnostic must fail the quality contract."""
    manifest = tmp_path / "quality.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "hallucination",
                        "command": "custom",
                        "text": "real line\n" * 100,
                        "must_preserve": ["real line"],
                        "must_not_contain": ["FABRICATED_DIAGNOSTIC"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "acco.output_quality.process_output",
        lambda *args, **kwargs: OutputResult(
            "real line\nFABRICATED_DIAGNOSTIC\n",
            "fake",
            True,
            False,
        ),
    )

    result = evaluate_quality_manifest(manifest)
    case = result["cases"][0]
    assert case["passed"] is False
    assert case["introduced_forbidden"] == ["FABRICATED_DIAGNOSTIC"]
    assert result["summary"]["no_hallucination_rate"] == 0.0



def test_quality_replay_enforces_expected_processor(tmp_path):
    """Frozen ratchets should fail when command routing changes unexpectedly."""
    manifest = tmp_path / "quality.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "routing",
                        "command": "git status",
                        "text": "On branch main\n" + ("hint\n" * 100),
                        "expected_processor": "git-log",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quality_manifest(manifest)
    case = report["cases"][0]
    assert case["processor"] == "git-status"
    assert case["expected_processor"] == "git-log"
    assert case["processor_ok"] is False
    assert case["passed"] is False
    assert report["summary"]["processor_match_rate"] == 0.0


def test_quality_replay_accepts_matching_expected_processor(tmp_path):
    """Matching processor identity should participate in a passing contract."""
    manifest = tmp_path / "quality.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "routing",
                        "command": "git status",
                        "text": "On branch main\n" + ("hint\n" * 100),
                        "expected_processor": "git-status",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_quality_manifest(manifest)
    case = report["cases"][0]
    assert case["processor_ok"] is True
    assert report["summary"]["processor_match_rate"] == 1.0

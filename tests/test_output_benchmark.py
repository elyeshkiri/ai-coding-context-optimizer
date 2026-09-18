import json

from token_saver.output_benchmark import evaluate_output_manifest


def test_output_benchmark_measures_reduction_and_preservation(tmp_path):
    manifest = tmp_path / "output.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "status",
            "text": (
                "Sure!\n\nImplemented the fix.\n\nImplemented the fix.\n\n"
                "```diff\n- old\n+ new\n```\n\n"
                "Tests: 42 passed.\n\nTests: 42 passed.\n"
            ),
            "mode": "terse",
            "must_contain": ["Implemented the fix.", "+ new", "Tests: 42 passed."],
        }]
    }), encoding="utf-8")

    result = evaluate_output_manifest(manifest)
    case = result["cases"][0]
    summary = result["summary"]

    assert case["output_tokens"] < case["original_tokens"]
    assert case["code_preserved"] is True
    assert case["required_content_preserved"] is True
    assert case["missing_required"] == []
    assert summary["weighted_token_reduction"] > 0
    assert summary["code_preservation_rate"] == 1.0
    assert summary["required_content_preservation_rate"] == 1.0


def test_output_benchmark_reports_budget_overflow_without_cutting_code(tmp_path):
    manifest = tmp_path / "output.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "large-code",
            "text": "```text\n" + ("important-output\n" * 50) + "```",
            "mode": "terse",
            "max_tokens": 20,
            "enforce_budget": True,
            "must_contain": ["important-output"],
        }]
    }), encoding="utf-8")

    result = evaluate_output_manifest(manifest)
    case = result["cases"][0]
    assert case["budget_exceeded"] is True
    assert case["code_preserved"] is True
    assert case["required_content_preserved"] is True


def test_output_benchmark_can_read_case_text_from_file(tmp_path):
    response = tmp_path / "response.md"
    response.write_text("Done.\n\nDone.\n", encoding="utf-8")
    manifest = tmp_path / "output.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "file-case",
            "path": "response.md",
            "mode": "terse",
        }]
    }), encoding="utf-8")

    result = evaluate_output_manifest(manifest)
    assert result["cases"][0]["removed_units"] >= 1

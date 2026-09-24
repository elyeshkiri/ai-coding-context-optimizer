"""Tests for historical ACCO learning/opportunity analysis."""

from __future__ import annotations

import json

from acco.command_handlers.efficiency import learn_main
from acco.learn import learn_report


def _assistant(message_id, tool_id, name, tool_input, usage=None):
    """Build one assistant tool-use transcript record."""
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": "synthetic",
            "usage": usage
            or {
                "input_tokens": 100,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 300,
                "output_tokens": 30,
            },
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": tool_input,
                }
            ],
        },
    }


def _result(tool_id, payload):
    """Build one tool-result transcript record."""
    return {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tool_id}]
        },
        "toolUseResult": payload,
    }


def _transcript(tmp_path):
    """Create local evidence with repeat reads and an identical failed retry."""
    code = "def handler(req, timeout=1.0):\n" + "    work()\n" * 160
    rows = [
        _assistant("m1", "r1", "Read", {"file_path": "src/app.py"}),
        _result("r1", {"file": {"filePath": "src/app.py", "content": code}}),
        _assistant("m2", "r2", "Read", {"file_path": "src/app.py"}),
        _result("r2", {"file": {"filePath": "src/app.py", "content": code}}),
        _assistant("m3", "b1", "Bash", {"command": "pytest -q"}),
        _result(
            "b1",
            {"stdout": "FAILED same assertion", "stderr": "", "exitCode": 1},
        ),
        _assistant("m4", "b2", "Bash", {"command": "pytest   -q"}),
        _result(
            "b2",
            {"stdout": "FAILED same assertion", "stderr": "", "exitCode": 1},
        ),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_learn_report_ranks_evidence_without_calling_it_savings(tmp_path):
    """Historical analysis should surface opportunities with explicit caveats."""
    root = tmp_path / "repo"
    root.mkdir()
    transcript = _transcript(tmp_path)

    report = learn_report(
        root,
        days=30,
        top=8,
        user_scope=False,
        paths=[transcript],
    )

    ids = [item["id"] for item in report["opportunities"]]
    assert report["sessions"] == 1
    assert report["turns"] == 4
    assert report["usage"]["cache_read_input_tokens"] == 1200
    assert report["duplicate_reads"]["estimated_tokens"] > 0
    assert report["outline"]["estimated_reduction"] > 0
    assert report["behavior"]["retry_attempts"] == 1
    assert "duplicate-reads" in ids
    assert "outline-source" in ids
    assert "tool-output" in ids
    assert "retry-loops" in ids
    assert report["evidence"]["provider_usage_measured"] is True
    assert report["evidence"]["tool_result_sizes_estimated"] is True
    assert report["evidence"]["savings_claim"] is False


def test_learn_cli_json_uses_project_history_loader(
    tmp_path, monkeypatch, capsys
):
    """The CLI should expose the same structured evidence without network work."""
    root = tmp_path / "repo"
    root.mkdir()
    transcript = _transcript(tmp_path)
    monkeypatch.setattr(
        "acco.learn._recent_paths",
        lambda _root, _days: [transcript],
    )

    assert learn_main([str(root), "--project-only", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["root"] == str(root.resolve())
    assert payload["transcripts"] == 1
    assert payload["evidence"]["task_success_verified"] is False
    assert payload["evidence"]["quality_verified"] is False


def test_learn_fails_honestly_without_history(tmp_path, monkeypatch, capsys):
    """No transcript evidence should be an explicit error, not an empty score."""
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr("acco.learn._recent_paths", lambda _root, _days: [])

    assert learn_main([str(root)]) == 2

    assert "no Claude session transcripts found" in capsys.readouterr().err

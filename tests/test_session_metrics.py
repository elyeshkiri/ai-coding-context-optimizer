"""Tests for independent transcript-derived session metrics."""

from __future__ import annotations

import json

from token_saver.session_metrics import (
    efficiency_event_metrics,
    transcript_session_metrics,
)


def _assistant(message_id: str, tool_id: str, name: str, tool_input: dict) -> dict:
    """Build one assistant tool-use transcript record."""
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": "synthetic",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 2,
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


def _result(tool_id: str, value: object) -> dict:
    """Build one tool-result transcript record."""
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "result",
                }
            ]
        },
        "toolUseResult": value,
    }


def test_transcript_metrics_count_retries_repeated_commands_and_reads(tmp_path):
    """Retry/read outcomes should be measured from raw transcript evidence."""
    transcript = tmp_path / "session.jsonl"
    rows = [
        _assistant("m1", "b1", "Bash", {"command": "pytest tests/test_bug.py -q"}),
        _result("b1", {"stdout": "FAILED same assertion", "stderr": "", "exitCode": 1}),
        _assistant("m2", "b2", "Bash", {"command": "pytest   tests/test_bug.py   -q"}),
        _result("b2", {"stdout": "FAILED same assertion", "stderr": "", "exitCode": 1}),
        _assistant("m3", "r1", "Read", {"file_path": "src/app.py"}),
        _result(
            "r1",
            {"file": {"filePath": "src/app.py", "content": "def f():\n    return 1\n"}},
        ),
        _assistant("m4", "r2", "Read", {"file_path": "src/app.py"}),
        _result(
            "r2",
            {"file": {"filePath": "src/app.py", "content": "def f():\n    return 1\n"}},
        ),
    ]
    transcript.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    metrics = transcript_session_metrics(transcript)

    assert metrics["tool_calls"] == 4
    assert metrics["bash_calls"] == 2
    assert metrics["unique_bash_commands"] == 1
    assert metrics["repeat_command_calls"] == 1
    assert metrics["retry_attempts"] == 1
    assert metrics["duplicate_read_calls"] == 1


def test_efficiency_event_metrics_keep_interventions_separate_from_outcomes(tmp_path):
    """Treatment events should summarize activation without becoming outcome truth."""
    root = tmp_path / "state"
    directory = root / "efficiency"
    directory.mkdir(parents=True)
    events = [
        {
            "schema": 1,
            "kind": "saving",
            "feature": "cross_turn_dedup",
            "estimated_tokens_saved": 50,
        },
        {
            "schema": 1,
            "kind": "saving",
            "feature": "unchanged_read_block",
            "estimated_tokens_saved": 30,
        },
        {"schema": 1, "kind": "waste", "feature": "retry_loop"},
        {"schema": 1, "kind": "waste", "feature": "tool_cascade"},
        {"schema": 1, "kind": "continuity", "feature": "checkpoint_restore"},
    ]
    (directory / "fixture.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events),
        encoding="utf-8",
    )

    metrics = efficiency_event_metrics(root)

    assert metrics["dedup_interventions"] == 2
    assert metrics["continuity_restores"] == 1
    assert metrics["waste_signals"] == 2
    assert metrics["retry_loop_signals"] == 1
    assert metrics["estimated_tool_context_tokens_saved"] == 80

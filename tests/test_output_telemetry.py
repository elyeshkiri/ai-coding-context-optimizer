"""Tests for local content-free output-budget telemetry."""

from __future__ import annotations

import json

import pytest

from token_saver.command_handlers.output import output_telemetry_main
from token_saver.output_telemetry import (
    finish_output_turn,
    load_output_telemetry,
    output_telemetry_report,
    start_output_turn,
    telemetry_path,
)
from token_saver.state import reset_session
from token_saver.state import update as update_state


def _assistant(message_id: str, output_tokens: int, *, model: str = "claude-test") -> dict:
    """Build one assistant transcript record with real usage-shaped counters."""
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": model,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30,
                "output_tokens": output_tokens,
            },
            "content": [{"type": "text", "text": "not persisted by telemetry"}],
        },
    }


def _set_policy(root, session_id: str, **overrides) -> None:
    """Store one active output-policy snapshot for a telemetry fixture."""
    policy = {
        "task": "coding",
        "mode": "normal",
        "max_tokens": 500,
        "adaptive": True,
        "complexity_score": 1,
        "complexity_tier": "standard",
        "calibrated": False,
        "calibration_samples": 0,
    }
    policy.update(overrides)

    def mutate(data):
        data["output_policy"] = policy

    update_state(root, mutate, session_id)


def test_turn_telemetry_measures_only_transcript_bytes_after_prompt(tmp_path, monkeypatch):
    """Prompt checkpoints should exclude earlier turns and dedupe repeated message blocks."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps(_assistant("old", 999)) + "\n", encoding="utf-8")
    _set_policy(root, "s1")

    start_output_turn(
        root,
        transcript_path=transcript,
        session_id="s1",
        prompt_id="prompt-1",
    )
    with transcript.open("a", encoding="utf-8") as handle:
        # Claude may repeat the same message usage for multiple content blocks.
        handle.write(json.dumps(_assistant("m1", 200)) + "\n")
        handle.write(json.dumps(_assistant("m1", 200)) + "\n")
        handle.write(json.dumps(_assistant("m2", 50)) + "\n")

    record = finish_output_turn(
        root,
        transcript_path=transcript,
        session_id="s1",
    )

    assert record is not None
    assert record["usage_available"] is True
    assert record["output_tokens"] == 250
    assert record["input_tokens"] == 20
    assert record["cache_creation_input_tokens"] == 40
    assert record["cache_read_input_tokens"] == 60
    assert record["model_calls"] == 2
    assert record["selected_budget"] == 500
    assert record["budget_utilization"] == pytest.approx(0.5)
    assert record["target_met"] is True
    assert record["turn_status"] == "completed"


def test_telemetry_never_persists_prompt_or_response_content(tmp_path, monkeypatch):
    """Telemetry should retain policy/usage metadata but no user or assistant text."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    _set_policy(root, "secret-session")

    start_output_turn(
        root,
        transcript_path=transcript,
        session_id="secret-session",
        prompt_id="prompt-id-is-metadata",
    )
    secret_response = _assistant("m1", 100)
    secret_response["message"]["content"][0]["text"] = "VERY SECRET ASSISTANT CONTENT"
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(secret_response) + "\n")

    finish_output_turn(
        root,
        transcript_path=transcript,
        session_id="secret-session",
    )

    serialized = telemetry_path(root).read_text(encoding="utf-8")
    assert "VERY SECRET ASSISTANT CONTENT" not in serialized
    assert "secret-session" not in serialized
    records = load_output_telemetry(root)
    assert records[0]["task_success"] is None
    assert records[0]["quality_verified"] is False


def test_stop_failure_is_recorded_as_api_failure_not_task_failure(tmp_path, monkeypatch):
    """Host API failure is distinct from independently verified task success."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    _set_policy(root, "s1")
    start_output_turn(root, transcript_path=transcript, session_id="s1")

    record = finish_output_turn(
        root,
        transcript_path=transcript,
        session_id="s1",
        status="api_failure",
        error="max_output_tokens",
    )

    assert record is not None
    assert record["turn_status"] == "api_failure"
    assert record["error"] == "max_output_tokens"
    assert record["task_success"] is None


def test_finish_without_pending_checkpoint_is_a_noop(tmp_path, monkeypatch):
    """Duplicate or unrelated Stop hooks must not create duplicate records."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    assert finish_output_turn(
        root,
        transcript_path=tmp_path / "missing.jsonl",
        session_id="s1",
    ) is None
    assert load_output_telemetry(root) == []


def test_report_flags_budget_patterns_as_observational_only(tmp_path, monkeypatch):
    """Effectiveness signals should summarize usage without claiming quality."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    path = telemetry_path(root)
    path.parent.mkdir(parents=True)
    records = []
    for i in range(5):
        records.append(
            {
                "schema": 1,
                "turn_status": "completed",
                "task": "coding",
                "mode": "normal",
                "selected_budget": 1000,
                "usage_available": True,
                "output_tokens": 300 + i * 10,
                "model_calls": 1,
                "budget_utilization": (300 + i * 10) / 1000,
                "target_met": True,
            }
        )
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    report = output_telemetry_report(root)

    assert report["summary"]["measured_turns"] == 5
    assert report["summary"]["target_met_rate"] == 1.0
    assert report["signals"]["underused_budget_groups"] == ["coding:normal"]
    assert report["signals"]["observational_only"] is True
    assert report["evidence_limits"]["task_success_evidence"] is False
    assert report["evidence_limits"]["quality_evidence"] is False


def test_output_telemetry_cli_emits_json_and_recent_records(tmp_path, monkeypatch, capsys):
    """The CLI should expose aggregate telemetry and bounded raw metadata records."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    path = telemetry_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "turn_status": "completed",
                "task": "review",
                "mode": "terse",
                "selected_budget": 300,
                "usage_available": True,
                "output_tokens": 200,
                "model_calls": 1,
                "budget_utilization": 2 / 3,
                "target_met": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert output_telemetry_main([str(root), "--json", "--records", "--limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["turns"] == 1
    assert len(payload["records"]) == 1
    assert payload["records"][0]["task"] == "review"


def test_session_reset_discards_pending_turn_instead_of_emitting_empty_record(
    tmp_path, monkeypatch
):
    """Resume/clear boundaries must not let stale checkpoints leak into later Stops."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    _set_policy(root, "s1")
    start_output_turn(root, transcript_path=transcript, session_id="s1")

    reset_session(root, reads=False, reminder=True, session_id="s1")

    assert finish_output_turn(
        root,
        transcript_path=transcript,
        session_id="s1",
    ) is None
    assert load_output_telemetry(root) == []


def test_report_skips_malformed_numeric_fields_in_valid_schema_records(
    tmp_path, monkeypatch
):
    """A hand-edited numeric field should not make the whole report unusable."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    path = telemetry_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "schema": 1,
            "turn_status": "completed",
            "task": "coding",
            "mode": "normal",
            "selected_budget": "not-a-number",
            "usage_available": True,
            "input_tokens": "broken",
            "output_tokens": 120,
            "model_calls": None,
            "budget_utilization": "broken",
            "target_met": None,
        }) + "\n",
        encoding="utf-8",
    )

    report = output_telemetry_report(root)

    assert report["summary"]["turns"] == 1
    assert report["summary"]["input_tokens"] == 0
    assert report["summary"]["output_tokens"] == 120
    assert report["summary"]["mean_selected_budget"] is None



def test_turn_telemetry_preserves_cache_creation_ttl_breakdown(tmp_path, monkeypatch):
    """Claude cache-write TTL buckets should survive transcript telemetry parsing."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("", encoding="utf-8")
    _set_policy(root, "s1")
    start_output_turn(root, transcript_path=transcript, session_id="s1")

    record = _assistant("m1", 100)
    record["message"]["usage"]["cache_creation"] = {
        "ephemeral_5m_input_tokens": 12,
        "ephemeral_1h_input_tokens": 8,
    }
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")

    measured = finish_output_turn(
        root,
        transcript_path=transcript,
        session_id="s1",
    )

    assert measured is not None
    assert measured["cache_creation_input_tokens"] == 20
    assert measured["cache_creation_5m_input_tokens"] == 12
    assert measured["cache_creation_1h_input_tokens"] == 8

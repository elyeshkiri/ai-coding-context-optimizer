"""Tests for session continuity, exact deduplication, and waste telemetry."""

from __future__ import annotations

from pathlib import Path

from acco.efficiency import (
    continuity_context,
    continuity_report,
    dashboard_report,
    deduplicate_output,
    observe_prompt,
    observe_tool,
    start_session,
)
from acco.efficiency.store import append_event, load_snapshot


def _root(tmp_path, monkeypatch) -> Path:
    """Create an isolated project and private ACCO state directory."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_continuity_persists_structure_without_prompt_or_output_text(
    tmp_path, monkeypatch
):
    """Continuity state should orient a resume without recording conversation text."""
    root = _root(tmp_path, monkeypatch)
    source = root / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def refresh():\n    return True\n", encoding="utf-8")

    start_session(root, session_id="s1", source="startup")
    observe_prompt(
        root,
        "Implement refresh-token fix password=super-secret",
        session_id="s1",
    )
    observe_tool(
        root,
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": str(source)},
        },
    )
    observe_tool(
        root,
        {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {
                "command": "TOKEN=top-secret pytest tests/test_auth.py -q"
            },
        },
        original_text="1 failed\n",
        delivered_text="1 failed\n",
        failed=True,
    )

    report = continuity_report(root)
    snapshot_text = next((tmp_path / "state" / "efficiency").glob("*.json")).read_text(
        encoding="utf-8"
    )

    assert report["available"] is True
    assert report["task"] == "coding"
    assert report["working_files"][-1]["path"] == "src/auth.py"
    assert "TOKEN=<redacted>" in report["commands"][-1]["label"]
    assert "top-secret" not in snapshot_text
    assert "refresh-token fix" not in snapshot_text
    assert "1 failed" not in snapshot_text

    context = continuity_context(
        root,
        session_id="new-session",
        source="resume",
    )
    assert context is not None
    assert "src/auth.py" in context
    assert "test=failed" in context
    assert "structured local state, not a transcript" in context


def test_exact_command_output_dedup_requires_same_command_and_output(
    tmp_path, monkeypatch
):
    """Only exact repeated output for the same command should collapse."""
    root = _root(tmp_path, monkeypatch)
    text = "\n".join(f"row {index}" for index in range(500))

    assert deduplicate_output(root, "git status", text, session_id="s1") is None
    duplicate = deduplicate_output(root, "git status", text, session_id="s1")
    assert duplicate is not None
    assert "exact output unchanged" in duplicate
    assert deduplicate_output(
        root,
        "git status",
        text + "\nchanged",
        session_id="s1",
    ) is None
    assert deduplicate_output(root, "git log", text, session_id="s1") is None


def test_retry_loop_and_tool_cascade_emit_bounded_behavior_signals(
    tmp_path, monkeypatch
):
    """Repeated failures and tool cascades should nudge once per turn."""
    root = _root(tmp_path, monkeypatch)
    observe_prompt(root, "debug the failure", session_id="s1")
    payload = {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest tests/test_bug.py -q"},
    }

    notes = [
        observe_tool(
            root,
            payload,
            original_text="FAILED same assertion",
            delivered_text="FAILED same assertion",
            failed=True,
        )
        for _ in range(4)
    ]

    assert notes[0] is None
    assert notes[1] is None
    assert "same failing command" in (notes[2] or "")
    assert notes[3] is None

    observe_prompt(root, "continue", session_id="s1")
    cascade_notes = []
    for index in range(12):
        cascade_notes.append(
            observe_tool(
                root,
                {
                    "session_id": "s1",
                    "tool_name": "Read",
                    "tool_input": {"file_path": f"src/file_{index}.py"},
                },
            )
        )
    assert "many tool calls" in (cascade_notes[-1] or "")


def test_dashboard_separates_savings_continuity_and_behavior(
    tmp_path, monkeypatch
):
    """Operational dashboard categories should remain explicit and local."""
    root = _root(tmp_path, monkeypatch)
    append_event(
        root,
        {
            "kind": "saving",
            "feature": "output_compression",
            "estimated_tokens_saved": 120,
        },
    )
    append_event(
        root,
        {
            "kind": "saving",
            "feature": "unchanged_read_block",
            "estimated_tokens_saved": 80,
        },
    )
    append_event(root, {"kind": "waste", "feature": "retry_loop"})
    append_event(root, {"kind": "continuity", "feature": "checkpoint_restore"})
    append_event(
        root,
        {
            "kind": "provider_usage",
            "feature": "provider_boundary",
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 500,
            "output_tokens": 50,
            "cache_read_input_tokens": 200,
            "streaming": True,
        },
    )
    append_event(
        root,
        {
            "kind": "provider_model_route",
            "feature": "model_routing",
            "applied": True,
            "from_model": "claude-sonnet-5",
            "to_model": "claude-haiku-4-5",
            "projected_savings_fraction": 0.6,
        },
    )

    report = dashboard_report(root, days=7)

    assert report["savings"]["estimated_tool_context_tokens"] == 200
    assert report["savings"]["by_feature"]["output_compression"] == 120
    assert report["behavior"]["signals"] == {"retry_loop": 1}
    assert report["continuity"]["restores"] == 1
    assert report["provider_usage"]["calls"] == 1
    assert report["provider_usage"]["input_tokens"] == 500
    assert report["provider_usage"]["output_tokens"] == 50
    assert report["provider_usage"]["by_provider"] == {"openai": 1}
    assert report["provider_usage"]["models"] == {"gpt-test": 1}
    assert report["provider_usage"]["merged_with_billed_usage"] is False
    assert report["provider_model_routing"]["decisions"] == 1
    assert report["provider_model_routing"]["applied"] == 1
    assert report["provider_model_routing"]["applied_pairs"] == {
        "claude-sonnet-5->claude-haiku-4-5": 1
    }
    assert report["provider_model_routing"]["mean_projected_savings_fraction"] == 0.6
    assert report["evidence"]["task_success"] is False
    assert "not an API invoice" in report["savings"]["trust"]


def test_start_clear_discards_current_checkpoint_but_not_project_store(
    tmp_path, monkeypatch
):
    """Explicit clear should start a fresh working set for the active session."""
    root = _root(tmp_path, monkeypatch)
    observe_tool(
        root,
        {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/a.py"},
        },
    )
    assert load_snapshot(root)["sessions"]

    start_session(root, session_id="s1", source="clear")

    report = continuity_report(root)
    assert report["working_files"] == []
    assert report["commands"] == []



def test_command_labels_redact_flag_and_authorization_secrets(
    tmp_path, monkeypatch
):
    """Persisted command labels should redact common secret argument forms."""
    root = _root(tmp_path, monkeypatch)
    observe_tool(
        root,
        {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "curl --token super-secret "
                    "-H 'Authorization: Bearer bearer-secret' https://example.test"
                )
            },
        },
        original_text="ok",
        delivered_text="ok",
    )

    label = continuity_report(root)["commands"][-1]["label"]
    assert "super-secret" not in label
    assert "bearer-secret" not in label
    assert "<redacted>" in label


def test_repeat_command_detection_does_not_count_previous_turns(
    tmp_path, monkeypatch
):
    """Legitimate reuse across separate prompts should not trigger a loop signal."""
    root = _root(tmp_path, monkeypatch)
    payload = {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
    }
    for _ in range(2):
        observe_prompt(root, "continue debugging", session_id="s1")
        assert observe_tool(
            root,
            payload,
            original_text="1 passed",
            delivered_text="1 passed",
        ) is None

    observe_prompt(root, "try again", session_id="s1")
    assert observe_tool(
        root,
        payload,
        original_text="1 passed",
        delivered_text="1 passed",
    ) is None

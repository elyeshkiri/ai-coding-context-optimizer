"""Tests for local session-efficiency CLI surfaces."""

from __future__ import annotations

import json

from acco.command_handlers.efficiency import (
    cache_economics_main,
    continuity_main,
    dashboard_main,
)
from acco.efficiency import observe_prompt, observe_tool
from acco.efficiency.store import append_event


def test_dashboard_cli_writes_self_contained_html(tmp_path, monkeypatch, capsys):
    """The dashboard should be useful locally without a server or external assets."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    append_event(
        root,
        {
            "kind": "saving",
            "feature": "cross_turn_dedup",
            "estimated_tokens_saved": 321,
        },
    )
    html = tmp_path / "dashboard.html"

    assert dashboard_main([str(root), "--days", "7", "--html", str(html)]) == 0

    output = capsys.readouterr().out
    assert "estimated tool-context saved: 321 tokens" in output
    assert str(html.resolve()) in output
    rendered = html.read_text(encoding="utf-8")
    assert "<!doctype html>" in rendered
    assert "ACCO Dashboard" in rendered
    assert "cross turn dedup" in rendered
    assert "external assets" not in rendered


def test_dashboard_json_keeps_operational_evidence_boundary(
    tmp_path, monkeypatch, capsys
):
    """JSON dashboard output must not imply verified task-success savings."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    assert dashboard_main([str(root), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence"]["task_success"] is False
    assert payload["evidence"]["quality_verified"] is False


def test_continuity_cli_reports_structured_working_state(
    tmp_path, monkeypatch, capsys
):
    """Continuity inspection should expose structure without conversation content."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    observe_prompt(root, "implement login refresh", session_id="s1")
    observe_tool(
        root,
        {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/auth.py"},
        },
    )

    assert continuity_main([str(root), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is True
    assert payload["task"] == "coding"
    assert payload["working_files"][-1]["path"] == "src/auth.py"
    assert "No raw user prompt" in payload["privacy"]



def test_cache_economics_cli_reports_prefix_recreation_penalty(capsys):
    """The CLI should expose when rewriting cached history is more expensive."""
    assert cache_economics_main(
        [
            "--original-frontier-tokens",
            "1000",
            "--replacement-frontier-tokens",
            "100",
            "--cached-prefix-tokens",
            "10000",
            "--invalidates-cached-prefix",
            "--json",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["accepted"] is False
    assert payload["invalidates_cached_prefix"] is True
    assert payload["replacement_cost"] > payload["original_cost"]

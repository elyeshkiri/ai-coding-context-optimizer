"""Tests for the isolated Claude blind-grader adapter."""

from __future__ import annotations

import json

from token_saver import claude_grader


class _Proc:
    """Minimal subprocess result fixture."""

    returncode = 0
    stderr = ""
    stdout = json.dumps({"result": "{\"A\":{},\"B\":{}}"})


def test_claude_grader_disables_side_effect_tools(monkeypatch):
    """The blind judge should run as a pure evaluator with dangerous tools denied."""
    captured = {}
    monkeypatch.setattr(claude_grader.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "test-workspace")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(claude_grader.subprocess, "run", fake_run)

    result = claude_grader.run(
        model="claude-sonnet-5",
        image="grader:fixed",
        prompt="grade this",
    )

    assert result == '{"A":{},"B":{}}'
    command = captured["command"]
    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "plan"
    denied = command[command.index("--disallowedTools") + 1]
    for tool in ("Bash", "Read", "Write", "WebFetch", "WebSearch"):
        assert tool in denied
    assert captured["kwargs"]["check"] is False

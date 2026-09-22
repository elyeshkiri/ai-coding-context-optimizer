"""Tests for the isolated two-phase session holdout runner."""

from __future__ import annotations

import json
from types import SimpleNamespace

from acco.session_holdout_docker import (
    _base_docker,
    _continuity_checkpoint,
    _repository_status,
    _validate_result,
)


def test_session_runner_forwards_all_efficiency_switches(tmp_path, monkeypatch):
    """Frozen condition switches must cross the Docker boundary unchanged."""
    worktree = tmp_path / "repo"
    worktree.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state"
    for name, value in {
        "ACCO_EFFICIENCY": "1",
        "ACCO_CONTINUITY": "1",
        "ACCO_CROSS_TURN_DEDUP": "1",
        "ACCO_WASTE_DETECTION": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "acco.session_holdout_docker.os.getuid",
        lambda: 123,
    )
    monkeypatch.setattr(
        "acco.session_holdout_docker.os.getgid",
        lambda: 456,
    )

    command = _base_docker(
        worktree=worktree,
        home=home,
        state_dir=state,
        image="fixture:1",
    )

    assert ["--user", "123:456"] == command[
        command.index("--user") : command.index("--user") + 2
    ]
    for name in (
        "ACCO_EFFICIENCY",
        "ACCO_CONTINUITY",
        "ACCO_CROSS_TURN_DEDUP",
        "ACCO_WASTE_DETECTION",
    ):
        assert name in command
    assert f"{state.resolve()}:/acco-state" in command


def test_continuity_checkpoint_invokes_real_resume_hook(tmp_path, monkeypatch):
    """The benchmark boundary must use SessionStart:resume, not a fake summary."""
    worktree = tmp_path / "repo"
    worktree.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("ACCO_EFFICIENCY", "1")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["payload"] = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": "structured checkpoint",
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "acco.session_holdout_docker.subprocess.run",
        fake_run,
    )

    context = _continuity_checkpoint(
        worktree=worktree,
        state_dir=state,
        image="fixture:1",
        child_env={},
    )

    assert context == "structured checkpoint"
    assert seen["command"][-2:] == ["acco", "hook"]
    assert seen["payload"]["hook_event_name"] == "SessionStart"
    assert seen["payload"]["source"] == "resume"
    assert seen["payload"]["cwd"] == "/workspace"


def test_validate_result_rejects_api_failure_even_on_valid_json():
    """API failure envelopes must never count as completed benchmark phases."""
    try:
        _validate_result(
            json.dumps(
                {
                    "is_error": True,
                    "terminal_reason": "api_error",
                    "api_error_status": 429,
                    "result": "rate limited",
                }
            ),
            "phase 1",
        )
    except ValueError as exc:
        assert "Claude API failure" in str(exc)
    else:
        raise AssertionError("API failure envelope must be rejected")


def test_validate_result_accepts_multiline_json_envelope():
    """Pretty-printed Claude JSON should be parsed as one full envelope."""
    _validate_result(
        json.dumps(
            {
                "is_error": False,
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "result": "done",
            },
            indent=2,
        ),
        "phase 2",
    )



def test_repository_status_ignores_managed_claude_files_but_detects_agent_edits(
    tmp_path
):
    """Phase-1 mutation guard should ignore hook config but catch source edits."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
    )
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    claude = repo / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{}", encoding="utf-8")

    assert _repository_status(repo) == ()

    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    status = _repository_status(repo)

    assert len(status) == 1
    assert "app.py" in status[0]

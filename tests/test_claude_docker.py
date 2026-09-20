from types import SimpleNamespace

from token_saver.claude_docker import run


def test_isolated_runner_uses_host_uid_and_extracts_transcript(
    tmp_path, monkeypatch
):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setattr("token_saver.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("token_saver.claude_docker.os.getuid", lambda: 1234)
    monkeypatch.setattr("token_saver.claude_docker.os.getgid", lambda: 5678)

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env")
        claude_home = transcript.parent / "claude-home"
        session = claude_home / "projects" / "fixture" / "session.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("token_saver.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="token-saver-e2e-agent:2.1.276",
    ) == 0

    command = seen["command"]
    assert ["--user", "1234:5678"] == command[
        command.index("--user") : command.index("--user") + 2
    ]
    assert "HOME=/tmp" in command
    assert "ANTHROPIC_CUSTOM_HEADERS" in command
    assert seen["env"]["ANTHROPIC_CUSTOM_HEADERS"] == (
        "anthropic-workspace-id: ws_test"
    )
    assert f"{(transcript.parent / 'claude-home').resolve()}:/tmp/.claude" in command
    assert transcript.read_text(encoding="utf-8") == '{"type":"assistant"}\n'
    assert not (transcript.parent / "claude-home").exists()


def test_isolated_runner_cleans_home_when_transcript_is_missing(
    tmp_path, monkeypatch
):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setattr("token_saver.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")

    def fake_run(command, **_kwargs):
        claude_home = transcript.parent / "claude-home"
        (claude_home / "sessions").mkdir(parents=True)
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("token_saver.claude_docker.subprocess.run", fake_run)

    try:
        run(
            worktree=worktree,
            transcript=transcript,
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="token-saver-e2e-agent:2.1.276",
        )
    except ValueError as exc:
        assert "produced no transcript" in str(exc)
    else:
        raise AssertionError("expected transcript failure")

    assert not (transcript.parent / "claude-home").exists()


def test_isolated_runner_rejects_api_error_with_zero_exit(
    tmp_path, monkeypatch
):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setattr(
        "token_saver.claude_docker.shutil.which",
        lambda _name: "/usr/bin/docker",
    )

    def fake_run(command, **_kwargs):
        claude_home = transcript.parent / "claude-home"
        session = claude_home / "projects" / "fixture" / "session.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(
            '{"type":"assistant","message":{"model":"<synthetic>"}}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"is_error":true,"terminal_reason":"api_error",'
                '"api_error_status":400,"result":"workspace required",'
                '"usage":{"input_tokens":0,"output_tokens":0}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "token_saver.claude_docker.subprocess.run",
        fake_run,
    )

    try:
        run(
            worktree=worktree,
            transcript=transcript,
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="token-saver-e2e-agent:2.1.276",
        )
    except ValueError as exc:
        assert "Claude Code API failure" in str(exc)
    else:
        raise AssertionError("expected API failure")


def test_isolated_runner_requires_workspace_id(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(
        "token_saver.claude_docker.shutil.which",
        lambda _name: "/usr/bin/docker",
    )

    try:
        run(
            worktree=worktree,
            transcript=tmp_path / "transcript.jsonl",
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="token-saver-e2e-agent:2.1.276",
        )
    except ValueError as exc:
        assert "ANTHROPIC_WORKSPACE_ID" in str(exc)
    else:
        raise AssertionError("expected missing workspace failure")



def test_isolated_runner_mounts_external_state_for_telemetry(
    tmp_path, monkeypatch
):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")
    state_dir = tmp_path / "token-saver-state"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(state_dir))
    monkeypatch.setattr(
        "token_saver.claude_docker.shutil.which",
        lambda _name: "/usr/bin/docker",
    )
    seen = {}

    def fake_run(command, **_kwargs):
        seen["command"] = command
        claude_home = transcript.parent / "claude-home"
        session = claude_home / "projects" / "fixture" / "session.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(
            '{"type":"assistant","message":{"id":"m1","model":"claude-sonnet-5","usage":{"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":2},"content":[]}}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("token_saver.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="token-saver-e2e-agent:2.1.276",
    ) == 0

    command = seen["command"]
    assert f"{state_dir.resolve()}:/token-saver-state" in command
    assert "TOKEN_SAVER_STATE_DIR=/token-saver-state" in command
    assert state_dir.is_dir()

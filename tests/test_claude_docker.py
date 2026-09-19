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
    monkeypatch.setattr("token_saver.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("token_saver.claude_docker.os.getuid", lambda: 1234)
    monkeypatch.setattr("token_saver.claude_docker.os.getgid", lambda: 5678)

    seen = {}

    def fake_run(command, check=False):
        seen["command"] = command
        claude_home = transcript.parent / "claude-home"
        session = claude_home / "projects" / "fixture" / "session.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(returncode=0)

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
    monkeypatch.setattr("token_saver.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")

    def fake_run(command, check=False):
        claude_home = transcript.parent / "claude-home"
        (claude_home / "sessions").mkdir(parents=True)
        return SimpleNamespace(returncode=1)

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

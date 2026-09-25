from types import SimpleNamespace

from acco.claude_docker import run


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
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("acco.claude_docker.os.getuid", lambda: 1234)
    monkeypatch.setattr("acco.claude_docker.os.getgid", lambda: 5678)

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

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
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
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")

    def fake_run(command, **_kwargs):
        claude_home = transcript.parent / "claude-home"
        (claude_home / "sessions").mkdir(parents=True)
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    try:
        run(
            worktree=worktree,
            transcript=transcript,
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="acco-e2e-agent:2.1.276",
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
        "acco.claude_docker.shutil.which",
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
        "acco.claude_docker.subprocess.run",
        fake_run,
    )

    try:
        run(
            worktree=worktree,
            transcript=transcript,
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="acco-e2e-agent:2.1.276",
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
        "acco.claude_docker.shutil.which",
        lambda _name: "/usr/bin/docker",
    )

    try:
        run(
            worktree=worktree,
            transcript=tmp_path / "transcript.jsonl",
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="acco-e2e-agent:2.1.276",
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
    state_dir = tmp_path / "acco-state"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setenv("ACCO_STATE_DIR", str(state_dir))
    monkeypatch.setattr(
        "acco.claude_docker.shutil.which",
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

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
    ) == 0

    command = seen["command"]
    assert f"{state_dir.resolve()}:/acco-state" in command
    assert "ACCO_STATE_DIR=/acco-state" in command
    assert state_dir.is_dir()


def _fake_claude(transcript, *, returncode, stdout, seen=None):
    """Return a docker stand-in that writes one session transcript."""

    def fake_run(command, **kwargs):
        if seen is not None:
            seen["command"] = command
            seen["env"] = kwargs.get("env")
        session = transcript.parent / "claude-home" / "projects" / "p" / "s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return fake_run


def _prepared(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    return worktree, tmp_path / "artifacts" / "transcript.jsonl", prompt


def test_subscription_runner_passes_only_oauth_token(tmp_path, monkeypatch):
    worktree, transcript, prompt = _prepared(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test")
    seen = {}
    monkeypatch.setattr(
        "acco.claude_docker.subprocess.run",
        _fake_claude(
            transcript,
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            seen=seen,
        ),
    )

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="baseline",
        image="acco-e2e-agent:2.1.276",
        auth="subscription",
    ) == 0

    command = seen["command"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" in command
    assert "ANTHROPIC_API_KEY" not in command
    assert "ANTHROPIC_CUSTOM_HEADERS" not in command


def test_subscription_runner_requires_oauth_token(tmp_path, monkeypatch):
    worktree, transcript, prompt = _prepared(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    try:
        run(
            worktree=worktree,
            transcript=transcript,
            prompt_file=prompt,
            model="claude-sonnet-5",
            condition="baseline",
            image="acco-e2e-agent:2.1.276",
            auth="subscription",
        )
    except ValueError as exc:
        assert "claude setup-token" in str(exc)
    else:
        raise AssertionError("expected missing-token failure")


def test_turn_limited_run_is_recorded_not_fatal(tmp_path, monkeypatch):
    worktree, transcript, prompt = _prepared(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setattr(
        "acco.claude_docker.subprocess.run",
        _fake_claude(
            transcript,
            returncode=1,
            stdout=(
                '{"subtype":"error_max_turns","is_error":true,'
                '"terminal_reason":"max_turns",'
                '"usage":{"input_tokens":10,"output_tokens":2}}\n'
            ),
        ),
    )

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
    ) == 0
    assert transcript.is_file()


def test_billing_failure_with_nonzero_exit_still_aborts(tmp_path, monkeypatch):
    worktree, transcript, prompt = _prepared(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "ws_test")
    monkeypatch.setattr(
        "acco.claude_docker.subprocess.run",
        _fake_claude(
            transcript,
            returncode=1,
            stdout=(
                '{"subtype":"success","is_error":true,'
                '"terminal_reason":"api_error",'
                '"result":"Credit balance is too low"}\n'
            ),
        ),
    )

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
    ) == 1


def test_isolated_runner_marks_root_container_as_sandbox(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("acco.claude_docker.os.getuid", lambda: 0)
    monkeypatch.setattr("acco.claude_docker.os.getgid", lambda: 0)

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        session = transcript.parent / "claude-home" / "projects" / "f" / "s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-haiku-4-5",
        condition="baseline",
        image="acco-e2e-agent:2.1.276",
        auth="subscription",
    ) == 0
    assert "IS_SANDBOX=1" in seen["command"]


def test_isolated_runner_forwards_output_policy_switch(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setenv("ACCO_OUTPUT_POLICY", "0")
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env")
        session = transcript.parent / "claude-home" / "projects" / "f" / "s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
        auth="subscription",
    ) == 0
    command = seen["command"]
    assert command[command.index("ACCO_OUTPUT_POLICY") - 1] == "-e"
    assert seen["env"]["ACCO_OUTPUT_POLICY"] == "0"


def test_isolated_runner_mounts_snapshot_over_task_repo(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix the bug.", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setattr("acco.claude_docker.shutil.which", lambda _name: "/usr/bin/docker")
    prepared = []
    monkeypatch.setattr(
        "acco.claude_docker.prepare_task_worktree",
        lambda path, image: prepared.append((path, image)),
    )
    monkeypatch.setattr(
        "acco.claude_docker.task_agent_image",
        lambda agent, task: f"derived-from-{task}",
    )

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        session = transcript.parent / "claude-home" / "projects" / "f" / "s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text('{"type":"assistant"}\n', encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout='{"is_error":false,"usage":{"input_tokens":10,"output_tokens":2}}\n',
            stderr="",
        )

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model="claude-sonnet-5",
        condition="enabled",
        image="acco-e2e-agent:2.1.276",
        auth="subscription",
        task_image="swebench/task:latest",
    ) == 0
    command = seen["command"]
    assert prepared == [(worktree, "swebench/task:latest")]
    assert "derived-from-swebench/task:latest" in command
    assert f"{worktree.resolve()}:/testbed" in command
    assert command[command.index("--workdir") + 1] == "/testbed"


def test_gitignore_literal_escapes_pattern_characters():
    from acco.claude_docker import _gitignore_literal

    assert _gitignore_literal("build/lib/a.so") == "/build/lib/a.so"
    assert _gitignore_literal("odd[1] #x!.py") == "/odd\\[1]\\ \\#x\\!.py"


def test_prepare_task_worktree_commits_environment_and_excludes_products(
    tmp_path, monkeypatch
):
    import io
    import subprocess as real_subprocess
    import tarfile

    from acco.claude_docker import prepare_task_worktree

    worktree = tmp_path / "repo"
    worktree.mkdir()
    (worktree / "setup.cfg").write_text("pin = old\n", encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "T"],
        ["add", "-A"],
        ["commit", "-q", "-m", "snapshot"],
    ):
        real_subprocess.run(["git", "-C", str(worktree), *args], check=True)

    env_patch = (
        b"diff --git a/setup.cfg b/setup.cfg\n"
        b"--- a/setup.cfg\n+++ b/setup.cfg\n"
        b"@@ -1 +1 @@\n-pin = old\n+pin = new\n"
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        body = b"\x7fELF"
        info = tarfile.TarInfo("pkg/_ext.so")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    archive.seek(0)

    real_run = real_subprocess.run

    def fake_run(command, **kwargs):
        if command[0] == "docker":
            return SimpleNamespace(returncode=0, stdout=env_patch, stderr=b"")
        return real_run(command, **kwargs)

    real_popen = real_subprocess.Popen

    class FakeDockerPopen:
        def __init__(self):
            self.stdout = archive
            self.stderr = io.BytesIO()

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        if command[0] == "docker":
            return FakeDockerPopen()
        return real_popen(command, **kwargs)

    monkeypatch.setattr("acco.claude_docker.subprocess.run", fake_run)
    monkeypatch.setattr("acco.claude_docker.subprocess.Popen", fake_popen)

    prepare_task_worktree(worktree, "swebench/task:latest")

    def git(*args):
        return real_run(
            ["git", "-C", str(worktree), *args], capture_output=True, text=True
        ).stdout

    assert git("log", "-1", "--format=%s").strip() == "SWE-bench environment"
    assert (worktree / "setup.cfg").read_text(encoding="utf-8") == "pin = new\n"
    assert (worktree / "pkg" / "_ext.so").read_bytes() == b"\x7fELF"
    assert git("status", "--porcelain") == ""

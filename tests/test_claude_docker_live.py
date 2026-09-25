"""Live smoke test for the isolated runner on a Claude Code subscription.

Skipped unless ACCO_LIVE_SUBSCRIPTION=1: it spends real subscription usage.

The token comes from CLAUDE_CODE_OAUTH_TOKEN, then ~/.acco-bench-token (both
from `claude setup-token`), then the access token of the host's current Claude
Code login. Only the access token is passed to the container, never the refresh
token, so the run cannot rotate or sign out the host session.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from acco.claude_docker import run

IMAGE = os.environ.get("ACCO_LIVE_IMAGE", "acco-e2e-agent:2.1.276")
MODEL = os.environ.get("ACCO_LIVE_MODEL", "claude-haiku-4-5")

pytestmark = pytest.mark.skipif(
    os.environ.get("ACCO_LIVE_SUBSCRIPTION") != "1",
    reason="set ACCO_LIVE_SUBSCRIPTION=1 to spend real subscription usage",
)


def _subscription_token() -> str | None:
    """Return the first available subscription OAuth token."""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    bench = Path.home() / ".acco-bench-token"
    if bench.is_file():
        return bench.read_text(encoding="utf-8").strip() or None
    credentials = Path.home() / ".claude" / ".credentials.json"
    if credentials.is_file():
        oauth = json.loads(credentials.read_text(encoding="utf-8")).get(
            "claudeAiOauth", {}
        )
        return oauth.get("accessToken") or None
    return None


def _image_available() -> bool:
    """Return whether Docker and the agent image are present locally."""
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
    )
    return proc.returncode == 0


def test_subscription_run_edits_worktree_and_records_usage(tmp_path, monkeypatch):
    token = _subscription_token()
    if not token:
        pytest.skip("no Claude Code subscription token found")
    if not _image_available():
        pytest.skip(f"docker image {IMAGE} is not available")

    worktree = tmp_path / "repo"
    worktree.mkdir()
    (worktree / "README.md").write_text("fixture\n", encoding="utf-8")
    transcript = tmp_path / "artifacts" / "transcript.jsonl"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(
        "Create a file named hello.txt in the current directory whose entire "
        "content is the single line: ok\nDo nothing else.",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert run(
        worktree=worktree,
        transcript=transcript,
        prompt_file=prompt,
        model=MODEL,
        condition="baseline",
        image=IMAGE,
        auth="subscription",
    ) == 0

    assert (worktree / "hello.txt").read_text(encoding="utf-8").strip() == "ok"
    events = [
        json.loads(line)
        for line in transcript.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    usages = [
        event["message"]["usage"]
        for event in events
        if event.get("type") == "assistant"
        and isinstance(event.get("message", {}).get("usage"), dict)
    ]
    assert usages, "transcript has no assistant usage to cost"
    assert sum(int(u.get("output_tokens") or 0) for u in usages) > 0
    assert not (transcript.parent / "claude-home").exists()

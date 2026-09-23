"""Run one Claude Code benchmark arm inside an isolated Docker container."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _docker_env(command: list[str], name: str) -> None:
    """Handle docker env."""
    if os.environ.get(name):
        command.extend(["-e", name])


def run(
    *,
    worktree: Path,
    transcript: Path,
    prompt_file: Path,
    model: str,
    condition: str,
    image: str,
) -> int:
    """Run the requested value."""
    if shutil.which("docker") is None:
        raise ValueError("Docker is required for the isolated Claude runner")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is required for Claude benchmark runs")
    if not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        raise ValueError(
            "ANTHROPIC_WORKSPACE_ID is required for this frozen benchmark key"
        )
    if condition not in {"baseline", "enabled"}:
        raise ValueError("condition must be baseline or enabled")
    if not worktree.is_dir() or not prompt_file.is_file():
        raise ValueError("benchmark worktree and prompt file must exist")

    prompt = prompt_file.read_text(encoding="utf-8")
    claude_home = transcript.parent / "claude-home"
    claude_home.mkdir(parents=True, exist_ok=True)

    uid = os.getuid()
    gid = os.getgid()
    child_env = os.environ.copy()
    child_env["ANTHROPIC_CUSTOM_HEADERS"] = (
        "anthropic-workspace-id: " + os.environ["ANTHROPIC_WORKSPACE_ID"]
    )
    command = [
        "docker", "run", "--rm",
        "--user", f"{uid}:{gid}",
        "--workdir", "/workspace",
        "-e", "HOME=/tmp",
        "-v", f"{worktree.resolve()}:/workspace",
        "-v", f"{claude_home.resolve()}:/tmp/.claude",
    ]
    state_dir = os.environ.get("ACCO_STATE_DIR")
    if state_dir:
        state_path = Path(state_dir).resolve()
        state_path.mkdir(parents=True, exist_ok=True)
        command.extend([
            "-v",
            f"{state_path}:/acco-state",
            "-e",
            "ACCO_STATE_DIR=/acco-state",
        ])
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_WORKSPACE_ID",
        "ACCO_DISABLED",
        "ACCO_BENCHMARK_CONDITION",
        "ACCO_BENCHMARK_TASK",
        "ACCO_BENCHMARK_TRIAL",
        "ACCO_EFFICIENCY",
        "ACCO_CONTINUITY",
        "ACCO_CROSS_TURN_DEDUP",
        "ACCO_WASTE_DETECTION",
    ):
        _docker_env(command, name)
    command.extend(["-e", "ANTHROPIC_CUSTOM_HEADERS"])
    command.extend([
        "-e", "DISABLE_AUTOUPDATER=1",
        image,
        "claude",
        "-p", prompt,
        "--model", model,
        "--dangerously-skip-permissions",
        "--max-turns", "50",
        "--output-format", "json",
    ])
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=os.sys.stderr)

    if proc.returncode != 0:
        return proc.returncode

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Claude Code returned exit 0 but no valid JSON result"
        ) from exc
    if not isinstance(result, dict):
        raise ValueError("Claude Code JSON result must be an object")
    if (
        result.get("is_error") is True
        or result.get("terminal_reason") == "api_error"
        or result.get("api_error_status") is not None
    ):
        detail = str(result.get("result") or result.get("terminal_reason") or "API error")
        raise ValueError(f"Claude Code API failure: {detail}")
    usage = result.get("usage")
    if not isinstance(usage, dict) or sum(
        int(usage.get(key) or 0)
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    ) <= 0:
        raise ValueError("Claude Code returned no billable model usage")

    try:
        paths = sorted((claude_home / "projects").rglob("*.jsonl"))
        if not paths:
            raise ValueError(
                "Claude Code produced no transcript; the run cannot be costed"
            )
        transcript.parent.mkdir(parents=True, exist_ok=True)
        with transcript.open("wb") as output:
            for path in paths:
                body = path.read_bytes()
                output.write(body)
                if body and not body.endswith(b"\n"):
                    output.write(b"\n")
    finally:
        # Keep only the evidence needed for accounting. Claude's private config
        # and session-home contents are not benchmark artifacts.
        shutil.rmtree(claude_home, ignore_errors=True)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    """Run the command-line entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    try:
        return run(
            worktree=Path(args.worktree),
            transcript=Path(args.transcript),
            prompt_file=Path(args.prompt_file),
            model=args.model,
            condition=args.condition,
            image=args.image,
        )
    except (OSError, ValueError) as exc:
        print(f"isolated Claude runner error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

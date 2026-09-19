"""Run one Claude Code benchmark arm inside an isolated Docker container."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def _docker_env(command: list[str], name: str) -> None:
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
    if shutil.which("docker") is None:
        raise ValueError("Docker is required for the isolated Claude runner")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is required for Claude benchmark runs")
    if condition not in {"baseline", "enabled"}:
        raise ValueError("condition must be baseline or enabled")
    if not worktree.is_dir() or not prompt_file.is_file():
        raise ValueError("benchmark worktree and prompt file must exist")

    prompt = prompt_file.read_text(encoding="utf-8")
    claude_home = transcript.parent / "claude-home"
    claude_home.mkdir(parents=True, exist_ok=True)

    uid = os.getuid()
    gid = os.getgid()
    command = [
        "docker", "run", "--rm",
        "--user", f"{uid}:{gid}",
        "--workdir", "/workspace",
        "-e", "HOME=/tmp",
        "-v", f"{worktree.resolve()}:/workspace",
        "-v", f"{claude_home.resolve()}:/tmp/.claude",
    ]
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_WORKSPACE_ID",
        "TOKEN_SAVER_DISABLED",
        "TOKEN_SAVER_BENCHMARK_CONDITION",
        "TOKEN_SAVER_BENCHMARK_TASK",
        "TOKEN_SAVER_BENCHMARK_TRIAL",
    ):
        _docker_env(command, name)
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
    proc = subprocess.run(command, check=False)

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

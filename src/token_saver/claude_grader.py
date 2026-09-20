"""Pinned Claude Code adapter for strict blind response grading."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys


def run(*, model: str, image: str, prompt: str) -> str:
    """Run one isolated Claude grading request and return its text result."""
    if shutil.which("docker") is None:
        raise ValueError("Docker is required for the isolated Claude grader")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is required for Claude grading")
    if not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        raise ValueError("ANTHROPIC_WORKSPACE_ID is required for Claude grading")

    uid = os.getuid()
    gid = os.getgid()
    child_env = os.environ.copy()
    child_env["ANTHROPIC_CUSTOM_HEADERS"] = (
        "anthropic-workspace-id: " + os.environ["ANTHROPIC_WORKSPACE_ID"]
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{uid}:{gid}",
        "--workdir",
        "/tmp",
        "-e",
        "HOME=/tmp",
        "-e",
        "ANTHROPIC_API_KEY",
        "-e",
        "ANTHROPIC_WORKSPACE_ID",
        "-e",
        "ANTHROPIC_CUSTOM_HEADERS",
        "-e",
        "DISABLE_AUTOUPDATER=1",
        image,
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--max-turns",
        "1",
        "--bare",
        "--disable-slash-commands",
        "--disallowedTools",
        "*",
        "--output-format",
        "json",
    ]
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )
    if proc.returncode:
        raise ValueError(
            f"Claude grader exited {proc.returncode}: {proc.stderr[-1500:]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except ValueError as exc:
        raise ValueError("Claude grader returned no valid JSON envelope") from exc
    if not isinstance(envelope, dict):
        raise ValueError("Claude grader JSON envelope must be an object")
    if (
        envelope.get("is_error") is True
        or envelope.get("terminal_reason") == "api_error"
        or envelope.get("api_error_status") is not None
    ):
        detail = str(
            envelope.get("result")
            or envelope.get("terminal_reason")
            or "API error"
        )
        raise ValueError(f"Claude grader API failure: {detail}")
    result = envelope.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Claude grader returned no textual result")
    return result.strip()


def main(argv: list[str] | None = None) -> int:
    """Run the isolated Claude blind-grader adapter."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("Claude grader requires a prompt on stdin", file=sys.stderr)
        return 2
    try:
        print(run(model=args.model, image=args.image, prompt=prompt))
    except (OSError, ValueError) as exc:
        print(f"isolated Claude grader error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

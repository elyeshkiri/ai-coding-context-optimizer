"""Run one two-phase session-efficiency holdout arm in isolated Claude containers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

PROTOCOL_VERSION = 1
_PHASE1_PREFIX = """You are in phase 1 of a frozen coding-agent benchmark.
Investigate the task thoroughly. Inspect relevant files and run diagnostics/tests
when useful, but do not edit or create repository files. Establish the likely
root cause and the concrete implementation/verification plan. Stop after
investigation; a fresh session will implement the fix.

FROZEN TASK:
"""
_PHASE2_PREFIX = """You are in phase 2 of a frozen coding-agent benchmark after
a forced fresh-session boundary. Complete the frozen task now. Verify the
repository state yourself; do not assume prior conversational context beyond
any structured host checkpoint explicitly included below.

FROZEN TASK:
"""


def _docker_env(command: list[str], name: str) -> None:
    """Forward one environment variable into Docker when present."""
    if os.environ.get(name) is not None:
        command.extend(["-e", name])


def _base_docker(
    *,
    worktree: Path,
    home: Path,
    state_dir: Path | None,
    image: str,
) -> list[str]:
    """Build the common isolated Docker command prefix."""
    uid = os.getuid()
    gid = os.getgid()
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{uid}:{gid}",
        "--workdir",
        "/workspace",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{worktree.resolve()}:/workspace",
        "-v",
        f"{home.resolve()}:/tmp/.claude",
    ]
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
        command.extend(
            [
                "-v",
                f"{state_dir.resolve()}:/token-saver-state",
                "-e",
                "TOKEN_SAVER_STATE_DIR=/token-saver-state",
            ]
        )
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_WORKSPACE_ID",
        "TOKEN_SAVER_DISABLED",
        "TOKEN_SAVER_BENCHMARK_CONDITION",
        "TOKEN_SAVER_BENCHMARK_TASK",
        "TOKEN_SAVER_BENCHMARK_TRIAL",
        "TOKEN_SAVER_EFFICIENCY",
        "TOKEN_SAVER_CONTINUITY",
        "TOKEN_SAVER_CROSS_TURN_DEDUP",
        "TOKEN_SAVER_WASTE_DETECTION",
    ):
        _docker_env(command, name)
    command.extend(["-e", "ANTHROPIC_CUSTOM_HEADERS"])
    return command


def _run_claude_phase(
    *,
    worktree: Path,
    home: Path,
    state_dir: Path | None,
    image: str,
    model: str,
    prompt: str,
    max_turns: int,
    investigation_only: bool,
    child_env: dict[str, str],
) -> tuple[int, str, str]:
    """Execute one isolated Claude phase and return code/stdout/stderr."""
    command = _base_docker(
        worktree=worktree,
        home=home,
        state_dir=state_dir,
        image=image,
    )
    command.extend(
        [
            "-e",
            "DISABLE_AUTOUPDATER=1",
            image,
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--dangerously-skip-permissions",
            "--max-turns",
            str(max_turns),
            "--output-format",
            "json",
        ]
    )
    if investigation_only:
        command.extend(["--tools", "Read,Grep,Glob,Bash"])
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _copy_transcripts(home: Path, destination: Path) -> None:
    """Append every Claude transcript from one phase to the run transcript."""
    paths = sorted((home / "projects").rglob("*.jsonl"))
    if not paths:
        raise ValueError("Claude phase produced no transcript")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("ab") as output:
        for path in paths:
            body = path.read_bytes()
            output.write(body)
            if body and not body.endswith(b"\n"):
                output.write(b"\n")


def _continuity_checkpoint(
    *,
    worktree: Path,
    state_dir: Path | None,
    image: str,
    child_env: dict[str, str],
) -> str | None:
    """Invoke the real SessionStart resume hook and return its additional context."""
    if state_dir is None:
        return None
    home = state_dir / "resume-hook-home"
    home.mkdir(parents=True, exist_ok=True)
    command = _base_docker(
        worktree=worktree,
        home=home,
        state_dir=state_dir,
        image=image,
    )
    command.extend([image, "token-saver", "hook"])
    payload = {
        "hook_event_name": "SessionStart",
        "cwd": "/workspace",
        "source": "resume",
        "session_id": str(uuid.uuid4()),
    }
    proc = subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )
    if proc.returncode:
        raise ValueError(
            "session holdout resume hook failed: " + proc.stderr[-1500:]
        )
    if not proc.stdout.strip():
        return None
    try:
        response = json.loads(proc.stdout)
    except ValueError as exc:
        raise ValueError("resume hook returned invalid JSON") from exc
    specific = response.get("hookSpecificOutput") if isinstance(response, dict) else None
    context = specific.get("additionalContext") if isinstance(specific, dict) else None
    return context if isinstance(context, str) and context.strip() else None


def _validate_result(stdout: str, phase: str) -> None:
    """Reject API-level Claude failures hidden behind process exit zero."""
    try:
        result = json.loads(stdout.splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{phase} returned no valid Claude JSON result") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{phase} Claude result must be an object")
    if (
        result.get("is_error") is True
        or result.get("terminal_reason") == "api_error"
        or result.get("api_error_status") is not None
    ):
        detail = str(result.get("result") or result.get("terminal_reason") or "API error")
        raise ValueError(f"{phase} Claude API failure: {detail}")


def run(
    *,
    worktree: Path,
    transcript: Path,
    prompt_file: Path,
    model: str,
    condition: str,
    image: str,
    phase1_turns: int,
    phase2_turns: int,
) -> int:
    """Run a frozen two-phase task with a forced fresh-session boundary."""
    if PROTOCOL_VERSION != 1:
        raise ValueError("unsupported session holdout protocol version")
    if shutil.which("docker") is None:
        raise ValueError("Docker is required for session holdout runs")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is required for session holdout runs")
    if not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        raise ValueError("ANTHROPIC_WORKSPACE_ID is required for session holdout runs")
    if condition not in {"baseline", "enabled"}:
        raise ValueError("condition must be baseline or enabled")
    if phase1_turns <= 0 or phase2_turns <= 0:
        raise ValueError("phase turn budgets must be positive")
    if not worktree.is_dir() or not prompt_file.is_file():
        raise ValueError("benchmark worktree and prompt file must exist")

    original_prompt = prompt_file.read_text(encoding="utf-8")
    state_raw = os.environ.get("TOKEN_SAVER_STATE_DIR")
    state_dir = Path(state_raw).resolve() if state_raw else None
    phase_root = transcript.parent / "session-phases"
    phase1_home = phase_root / "phase1-home"
    phase2_home = phase_root / "phase2-home"
    phase1_home.mkdir(parents=True, exist_ok=True)
    phase2_home.mkdir(parents=True, exist_ok=True)
    transcript.unlink(missing_ok=True)

    child_env = os.environ.copy()
    child_env["ANTHROPIC_CUSTOM_HEADERS"] = (
        "anthropic-workspace-id: " + os.environ["ANTHROPIC_WORKSPACE_ID"]
    )

    phase1_prompt = _PHASE1_PREFIX + original_prompt
    rc1, stdout1, stderr1 = _run_claude_phase(
        worktree=worktree,
        home=phase1_home,
        state_dir=state_dir,
        image=image,
        model=model,
        prompt=phase1_prompt,
        max_turns=phase1_turns,
        investigation_only=True,
        child_env=child_env,
    )
    if stdout1:
        print(stdout1, end="" if stdout1.endswith("\n") else "\n")
    if stderr1:
        print(stderr1, end="" if stderr1.endswith("\n") else "\n", file=os.sys.stderr)
    if rc1:
        return rc1
    _validate_result(stdout1, "phase 1")
    _copy_transcripts(phase1_home, transcript)

    checkpoint = _continuity_checkpoint(
        worktree=worktree,
        state_dir=state_dir,
        image=image,
        child_env=child_env,
    )
    phase2_prompt = _PHASE2_PREFIX + original_prompt
    if checkpoint:
        phase2_prompt += (
            "\n\nHOST CONTINUITY CHECKPOINT (orientation only):\n"
            + checkpoint
        )

    rc2, stdout2, stderr2 = _run_claude_phase(
        worktree=worktree,
        home=phase2_home,
        state_dir=state_dir,
        image=image,
        model=model,
        prompt=phase2_prompt,
        max_turns=phase2_turns,
        investigation_only=False,
        child_env=child_env,
    )
    if stdout2:
        print(stdout2, end="" if stdout2.endswith("\n") else "\n")
    if stderr2:
        print(stderr2, end="" if stderr2.endswith("\n") else "\n", file=os.sys.stderr)
    if rc2:
        return rc2
    _validate_result(stdout2, "phase 2")
    _copy_transcripts(phase2_home, transcript)

    shutil.rmtree(phase_root, ignore_errors=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the session-efficiency holdout container adapter."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--phase1-turns", type=int, default=12)
    parser.add_argument("--phase2-turns", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        return run(
            worktree=Path(args.worktree),
            transcript=Path(args.transcript),
            prompt_file=Path(args.prompt_file),
            model=args.model,
            condition=args.condition,
            image=args.image,
            phase1_turns=args.phase1_turns,
            phase2_turns=args.phase2_turns,
        )
    except (OSError, ValueError) as exc:
        print(f"session holdout runner error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

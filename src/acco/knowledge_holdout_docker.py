"""Run one frozen two-session knowledge-efficiency holdout arm."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from .efficiency.store import append_event
from .session_holdout_docker import (
    _copy_transcripts,
    _repository_status,
    _run_claude_phase,
    _validate_result,
)

PROTOCOL_VERSION = 1
_PHASE1_PREFIX = """You are in phase 1 of a frozen coding-agent benchmark.
Investigate the task thoroughly. Inspect relevant files and run diagnostics/tests
when useful, but do not edit or create repository files. Establish the likely
root cause and concrete implementation/verification plan.

Before stopping, persist 1 to 3 VERIFIED project findings with the installed
Token Saver CLI. Each finding must be grounded in a real source file you
inspected and useful to the implementation session. Use Bash commands in this
form, with repository-relative anchors:

token-saver remember . --claim "..." --anchor "path/to/file.py::symbol" --evidence "..." --applicability "..." --confidence verified

Do not store guesses. Stop after investigation and the finding writes; a fresh
session will implement the fix.

FROZEN TASK:
"""
_PHASE2_PREFIX = """You are in phase 2 of a frozen coding-agent benchmark after
a forced fresh-session boundary. Complete the frozen task now. Verify repository
state as needed and use normal coding-agent behavior. Do not assume prior
conversational context and do not inspect benchmark harness or hidden grader
files.

FROZEN TASK:
"""


def _knowledge_seed_count(state_dir: Path) -> int:
    """Count verified findings written into the isolated benchmark state."""
    directory = state_dir / "knowledge"
    if not directory.is_dir():
        return 0
    count = 0
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(findings, list):
            continue
        count += sum(
            isinstance(item, dict)
            and item.get("confidence") == "verified"
            and not item.get("superseded_by")
            for item in findings
        )
    return count


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
    """Run an isolated investigation-to-implementation knowledge experiment."""
    if PROTOCOL_VERSION != 1:
        raise ValueError("unsupported knowledge holdout protocol version")
    if shutil.which("docker") is None:
        raise ValueError("Docker is required for knowledge holdout runs")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is required for knowledge holdout runs")
    if not os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        raise ValueError("ANTHROPIC_WORKSPACE_ID is required for knowledge holdout runs")
    if condition not in {"baseline", "enabled"}:
        raise ValueError("condition must be baseline or enabled")
    if phase1_turns <= 0 or phase2_turns <= 0:
        raise ValueError("phase turn budgets must be positive")
    if not worktree.is_dir() or not prompt_file.is_file():
        raise ValueError("benchmark worktree and prompt file must exist")

    state_raw = os.environ.get("TOKEN_SAVER_STATE_DIR")
    if not state_raw:
        raise ValueError("TOKEN_SAVER_STATE_DIR is required for knowledge holdout runs")
    state_dir = Path(state_raw).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)

    original_prompt = prompt_file.read_text(encoding="utf-8")
    phase_root = transcript.parent / "knowledge-phases"
    phase1_home = phase_root / "phase1-home"
    phase2_home = phase_root / "phase2-home"
    phase1_home.mkdir(parents=True, exist_ok=True)
    phase2_home.mkdir(parents=True, exist_ok=True)
    transcript.unlink(missing_ok=True)

    common_env = os.environ.copy()
    common_env["ANTHROPIC_CUSTOM_HEADERS"] = (
        "anthropic-workspace-id: " + os.environ["ANTHROPIC_WORKSPACE_ID"]
    )
    phase1_env = dict(common_env)
    phase1_env["TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE"] = "0"
    phase1_env["TOKEN_SAVER_CACHE_ECONOMICS"] = "0"

    status_before = _repository_status(worktree)
    rc1, stdout1, stderr1 = _run_claude_phase(
        worktree=worktree,
        home=phase1_home,
        state_dir=state_dir,
        image=image,
        model=model,
        prompt=_PHASE1_PREFIX + original_prompt,
        max_turns=phase1_turns,
        investigation_only=True,
        child_env=phase1_env,
    )
    if stdout1:
        print(stdout1, end="" if stdout1.endswith("\n") else "\n")
    if stderr1:
        print(stderr1, end="" if stderr1.endswith("\n") else "\n", file=os.sys.stderr)
    if rc1:
        return rc1
    _validate_result(stdout1, "phase 1")
    if _repository_status(worktree) != status_before:
        raise ValueError(
            "phase 1 modified benchmark repository state despite the "
            "investigation-only contract"
        )
    _copy_transcripts(phase1_home, transcript)

    seed_count = _knowledge_seed_count(state_dir)
    if seed_count < 1:
        raise ValueError("phase 1 produced no verified Token Saver project finding")
    append_event(
        worktree,
        {
            "kind": "knowledge",
            "feature": "finding_seed",
            "finding_count": seed_count,
        },
    )

    rc2, stdout2, stderr2 = _run_claude_phase(
        worktree=worktree,
        home=phase2_home,
        state_dir=state_dir,
        image=image,
        model=model,
        prompt=_PHASE2_PREFIX + original_prompt,
        max_turns=phase2_turns,
        investigation_only=False,
        child_env=common_env,
    )
    if stdout2:
        print(stdout2, end="" if stdout2.endswith("\n") else "\n")
    if stderr2:
        print(stderr2, end="" if stderr2.endswith("\n") else "\n", file=os.sys.stderr)
    if rc2:
        return rc2
    _validate_result(stdout2, "phase 2")
    _copy_transcripts(phase2_home, transcript)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the frozen knowledge-efficiency holdout container adapter."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--phase1-turns", type=int, default=14)
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
        print(f"knowledge holdout runner error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

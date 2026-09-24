"""User-facing paired A/B trials built on ACCO's experiment engine."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time

from .benchmark import task_definition_hash
from .experiment import prompt_sha256, run_experiment
from .state import state_dir

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_TIMEOUT = 1800


def _git(root: Path, *args: str) -> str:
    """Run one read-only Git command or raise a concise validation error."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed for {root}: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _parse_command(value: str, *, label: str) -> list[str]:
    """Parse one shell-like command into an argv array without using a shell."""
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label} command: {exc}") from exc
    if not command:
        raise ValueError(f"{label} command must not be empty")
    return command


def _default_output(root: Path, prompt: str) -> Path:
    """Return a private, collision-resistant path for one local trial."""
    project = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    prompt_id = prompt_sha256(prompt)[:10]
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    directory = state_dir() / "trials" / project
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / f"{stamp}-{prompt_id}.json"


def build_trial_suite(
    root: Path,
    *,
    prompt: str,
    verifier_commands: list[str],
    model: str = DEFAULT_MODEL,
    trials: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
    setup_commands: list[str] | None = None,
    runner_command: str | None = None,
    transcript_mode: str = "claude-project",
) -> dict:
    """Build a one-task development suite for a real baseline/ACCO comparison."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    if not prompt.strip():
        raise ValueError("trial prompt must not be empty")
    if not verifier_commands:
        raise ValueError("at least one --verify command is required")
    if trials < 1:
        raise ValueError("trials must be positive")
    if timeout < 1:
        raise ValueError("timeout must be positive")
    if not model.strip():
        raise ValueError("model must not be empty")
    if transcript_mode not in {"claude-project", "path"}:
        raise ValueError("transcript mode must be claude-project or path")

    revision = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    verifiers = [
        _parse_command(command, label="verifier")
        for command in verifier_commands
    ]
    setup = [
        _parse_command(command, label="setup")
        for command in (setup_commands or [])
    ]
    if runner_command:
        runner = _parse_command(runner_command, label="runner")
    else:
        runner = [
            "claude",
            "-p",
            "{prompt}",
            "--model",
            "{model}",
            "--dangerously-skip-permissions",
            "--max-turns",
            "50",
            "--output-format",
            "json",
        ]

    digest = hashlib.sha256(
        (revision + "\0" + prompt).encode("utf-8")
    ).hexdigest()
    task_id = "trial-" + digest[:12]
    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": False,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": False,
            "frozen_at": None,
            "trial_only": True,
            "task_definition_sha256": "",
        },
        "design": {
            "trials_per_task": trials,
            "condition_order_seed": int(digest[:8], 16),
        },
        "repositories": {
            "project": {
                "path": str(root),
                "revision": revision,
            }
        },
        "runner": {
            "command": runner,
            "model": model.strip(),
            "transcript_mode": transcript_mode,
            "timeout_seconds": timeout,
            "condition_profiles": {
                "baseline": {
                    "label": "without-acco",
                    "install_acco": False,
                    "env": {},
                },
                "enabled": {
                    "label": "with-acco",
                    "install_acco": True,
                    "env": {},
                },
            },
        },
        "tasks": [
            {
                "id": task_id,
                "repository": "project",
                "revision": revision,
                "prompt": prompt,
                "prompt_sha256": prompt_sha256(prompt),
                "setup": setup,
                "verifier": verifiers,
            }
        ],
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    return suite


def summarize_trial(payload: dict) -> dict:
    """Summarize paired runs without turning token deltas into a quality claim."""
    arms: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for run in payload.get("runs", []):
        if isinstance(run, dict) and run.get("condition") in {"baseline", "enabled"}:
            grouped[str(run["condition"])].append(run)

    for condition in ("baseline", "enabled"):
        runs = grouped.get(condition, [])
        successes = sum(run.get("success") is True for run in runs)
        input_tokens = sum(
            int(run.get("input_tokens") or 0)
            for run in runs
            if not isinstance(run.get("input_tokens"), bool)
        )
        output_tokens = sum(
            int(run.get("output_tokens") or 0)
            for run in runs
            if not isinstance(run.get("output_tokens"), bool)
        )
        tool_calls = sum(
            int(run.get("tool_calls") or 0)
            for run in runs
            if not isinstance(run.get("tool_calls"), bool)
        )
        seconds = sum(
            float(run.get("seconds") or 0)
            for run in runs
            if isinstance(run.get("seconds"), (int, float))
            and not isinstance(run.get("seconds"), bool)
        )
        arms[condition] = {
            "runs": len(runs),
            "successes": successes,
            "success_rate": successes / len(runs) if runs else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "tool_calls": tool_calls,
            "seconds": seconds,
            "input_tokens_per_success": (
                input_tokens / successes if successes else None
            ),
            "total_tokens_per_success": (
                (input_tokens + output_tokens) / successes
                if successes else None
            ),
        }

    def reduction(field: str) -> float | None:
        """Return the enabled reduction for a per-success metric."""
        baseline = arms["baseline"].get(field)
        enabled = arms["enabled"].get(field)
        if (
            not isinstance(baseline, (int, float))
            or isinstance(baseline, bool)
            or baseline <= 0
            or not isinstance(enabled, (int, float))
            or isinstance(enabled, bool)
        ):
            return None
        return 1.0 - float(enabled) / float(baseline)

    return {
        "conditions": arms,
        "comparison": {
            "input_tokens_per_success_reduction": reduction(
                "input_tokens_per_success"
            ),
            "total_tokens_per_success_reduction": reduction(
                "total_tokens_per_success"
            ),
        },
        "evidence": {
            "independent_task_verifier": True,
            "blind_response_quality": False,
            "frozen_broad_suite": False,
            "publishable": False,
            "claim_allowed": False,
            "note": (
                "This local trial is workload evidence, not a publishable general "
                "savings claim. Token deltas are only meaningful alongside the "
                "independent verifier result."
            ),
        },
    }


def run_trial(
    root: Path,
    *,
    prompt: str,
    verifier_commands: list[str],
    model: str = DEFAULT_MODEL,
    trials: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
    setup_commands: list[str] | None = None,
    runner_command: str | None = None,
    transcript_mode: str = "claude-project",
    output_path: Path | None = None,
    allow_dirty: bool = False,
    allow_user_hook: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run a simple local A/B while preserving the experiment engine's controls."""
    root = root.resolve()
    status = _git(root, "status", "--porcelain")
    if status and not allow_dirty:
        raise ValueError(
            "working tree is dirty; commit/stash changes before trial, or pass "
            "--allow-dirty to explicitly benchmark HEAD while ignoring them"
        )
    if runner_command is None and shutil.which("claude") is None:
        raise ValueError(
            "claude executable not found; install Claude Code or pass --runner "
            "with a command that produces the requested transcript"
        )

    suite = build_trial_suite(
        root,
        prompt=prompt,
        verifier_commands=verifier_commands,
        model=model,
        trials=trials,
        timeout=timeout,
        setup_commands=setup_commands,
        runner_command=runner_command,
        transcript_mode=transcript_mode,
    )
    output = (output_path or _default_output(root, prompt)).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    suite_path = output.with_name(output.stem + ".suite.json")
    suite_path.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")

    result = run_experiment(
        suite_path,
        output,
        dry_run=dry_run,
        allow_development=True,
        allow_user_hook=allow_user_hook,
    )
    response = {
        "schema": 1,
        "root": str(root),
        "revision": suite["tasks"][0]["revision"],
        "suite": str(suite_path),
        "manifest": None if dry_run else str(output),
        "dirty_worktree_ignored": bool(status),
        "trial": result,
    }
    if not dry_run:
        response["summary"] = summarize_trial(result)
    return response

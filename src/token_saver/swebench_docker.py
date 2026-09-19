"""Grade an agent patch inside an official SWE-bench evaluation image."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def verify_swebench(
    *,
    image: str,
    agent_patch: Path,
    test_patch: Path,
    test_command: str,
    env_activate: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
) -> tuple[int, float]:
    """Apply solution + hidden tests in the canonical container and grade them."""
    import time

    if shutil.which("docker") is None:
        raise ValueError(
            "Docker is required for SWE-bench verification but was not found"
        )
    if not image.strip() or not test_command.strip() or not env_activate.strip():
        raise ValueError("SWE-bench image, test command and env activation are required")

    # The official image already contains the repository and compatibility
    # adjustments at /testbed. Mount patches only; never replace /testbed with
    # the host checkout or the image's prepared environment would be lost.
    shell = (
        "set -euo pipefail; "
        "cd /testbed; "
        "if [ -s /tmp/token-saver-agent.patch ]; then "
        "  git apply --whitespace=nowarn /tmp/token-saver-agent.patch; "
        "fi; "
        "git apply --whitespace=nowarn /tmp/token-saver-test.patch; "
        f"{env_activate}; "
        f"{test_command}"
    )
    command = [
        "docker", "run", "--rm",
        "-v", f"{agent_patch.resolve()}:/tmp/token-saver-agent.patch:ro",
        "-v", f"{test_patch.resolve()}:/tmp/token-saver-test.patch:ro",
        image,
        "bash", "-lc", shell,
    ]

    start = time.monotonic()
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            proc = subprocess.run(
                command,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return 124, time.monotonic() - start
    return proc.returncode, time.monotonic() - start


_DIFF_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)
_STATUS_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)[ \t]+(\S.*)$")


def _patch_blocks(patch: str) -> list[str]:
    """Handle patch blocks."""
    return [b for b in re.split(r"(?=^diff --git )", patch, flags=re.M) if b.strip()]


def _patch_files(patch: str) -> set[str]:
    """Handle patch files."""
    return {name for pair in _DIFF_HEADER.findall(patch) for name in pair}


def strip_test_file_changes(agent_patch: str, test_patch: str) -> str:
    """Drop agent hunks for files the hidden test patch modifies.

    Applying the hidden tests on top of an agent's own edits to the same test
    file fails with "patch does not apply". Grading must judge the agent's
    source changes against the reference tests, so those test-file edits are
    removed before verification (the recorded agent patch is left untouched).
    """
    protected = _patch_files(test_patch)
    return "".join(
        block for block in _patch_blocks(agent_patch)
        if not _patch_files(block) & protected
    )


def parse_test_statuses(output: str) -> dict[str, str]:
    """Per-test outcome parsed from pytest ``-rA`` short-summary lines."""
    statuses: dict[str, str] = {}
    for line in output.splitlines():
        match = _STATUS_LINE.match(line)
        if not match:
            continue
        status, rest = match.groups()
        if status in {"FAILED", "ERROR"}:
            rest = rest.split(" - ", 1)[0]
        statuses[rest.strip()] = status
    return statuses


def passed_tests(output: str) -> set[str]:
    """Handle passed tests."""
    return {t for t, s in parse_test_statuses(output).items() if s == "PASSED"}


def grade_swebench(
    fail_to_pass: list[str],
    reference_passed: set[str],
    run_passed: set[str],
) -> dict:
    """Resolved iff every target test passes and nothing regresses.

    The whole-command exit code is not used: images can carry pre-existing
    errors (for example broken fixtures) that make it nonzero even for a
    correct fix. Regressions are measured against the unpatched reference run,
    which had the same hidden tests applied.
    """
    fixed = [t for t in fail_to_pass if t in run_passed]
    regressions = sorted(reference_passed - run_passed)
    return {
        "resolved": len(fixed) == len(fail_to_pass) and not regressions,
        "fail_to_pass_passed": len(fixed),
        "fail_to_pass_total": len(fail_to_pass),
        "regression_count": len(regressions),
        "regressions": regressions[:20],
    }

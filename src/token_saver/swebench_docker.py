"""Grade an agent patch inside an official SWE-bench evaluation image."""

from __future__ import annotations

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

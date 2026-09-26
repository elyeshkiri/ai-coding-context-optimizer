"""Low-friction provider-proxy wrapper for supported coding agents."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


@dataclass(frozen=True)
class HostPreset:
    """Describe one coding agent's provider-boundary configuration."""

    executable: str
    provider: str
    upstream: str
    base_url_env: str


PRESETS = {
    "claude": HostPreset(
        "claude",
        "anthropic",
        "https://api.anthropic.com",
        "ANTHROPIC_BASE_URL",
    ),
    "codex": HostPreset(
        "codex",
        "openai",
        "https://api.openai.com",
        "OPENAI_BASE_URL",
    ),
    "gemini": HostPreset(
        "gemini",
        "gemini",
        "https://generativelanguage.googleapis.com",
        "GOOGLE_GEMINI_BASE_URL",
    ),
}


@dataclass(frozen=True)
class WrapPlan:
    """A deterministic launch plan that can be inspected before execution."""

    agent: str
    executable: str
    provider: str
    upstream: str
    base_url_env: str
    bind: str
    port: int
    argv: tuple[str, ...]

    @property
    def local_base_url(self) -> str:
        base = f"http://{self.bind}:{self.port}"
        return base + "/v1" if self.provider == "openai" else base

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "executable": self.executable,
            "provider": self.provider,
            "upstream": self.upstream,
            "base_url_env": self.base_url_env,
            "local_base_url": self.local_base_url,
            "argv": list(self.argv),
        }


def _free_port(bind: str) -> int:
    """Reserve an ephemeral loopback port long enough to choose a launch port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind((bind, 0))
        return int(handle.getsockname()[1])


def build_wrap_plan(
    agent: str,
    agent_args: list[str],
    *,
    bind: str = "127.0.0.1",
    port: int = 0,
    provider: str | None = None,
    upstream: str | None = None,
    base_url_env: str | None = None,
    executable: str | None = None,
) -> WrapPlan:
    """Build a wrapper plan without launching a provider or child process."""
    preset = PRESETS.get(agent)
    if preset is None and not all((provider, upstream, base_url_env)):
        raise ValueError(
            "unknown agent requires --provider, --upstream, and --base-url-env"
        )
    selected_provider = provider or preset.provider
    selected_upstream = upstream or preset.upstream
    selected_env = base_url_env or preset.base_url_env
    selected_executable = executable or (preset.executable if preset else agent)
    selected_port = port or _free_port(bind)
    if selected_port <= 0 or selected_port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return WrapPlan(
        agent=agent,
        executable=selected_executable,
        provider=selected_provider,
        upstream=selected_upstream,
        base_url_env=selected_env,
        bind=bind,
        port=selected_port,
        argv=tuple(agent_args),
    )


def _wait_for_proxy(bind: str, port: int, timeout: float = 5.0) -> None:
    """Wait for the local proxy socket without sending provider traffic."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((bind, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("ACCO provider proxy did not become ready")


def run_wrap(
    root: Path,
    plan: WrapPlan,
    *,
    model_routing: str = "off",
) -> int:
    """Launch an ephemeral ACCO provider proxy and then the selected agent."""
    executable = shutil.which(plan.executable)
    if executable is None:
        raise FileNotFoundError(f"agent executable not found: {plan.executable}")

    proxy_argv = [
        sys.executable,
        "-m",
        "acco.entry",
        "provider-proxy",
        str(root.resolve()),
        "--upstream",
        plan.upstream,
        "--provider",
        plan.provider,
        "--bind",
        plan.bind,
        "--port",
        str(plan.port),
        "--model-routing",
        model_routing,
    ]
    proxy = subprocess.Popen(proxy_argv)
    try:
        _wait_for_proxy(plan.bind, plan.port)
        env = os.environ.copy()
        env[plan.base_url_env] = plan.local_base_url
        completed = subprocess.run(
            [executable, *plan.argv],
            env=env,
            cwd=root,
            check=False,
        )
        return int(completed.returncode)
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait(timeout=2)

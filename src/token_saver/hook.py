"""Claude Code JSON hook adapter.

This module translates Claude's stdin/stdout protocol and environment settings
into the host-neutral :mod:`token_saver.hook_runtime` application boundary.
Concrete services are composed here so the runtime itself stays independent of
Claude, environment variables, persistence, and repository implementations.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .delta_context import apply_delta
from .estimate import estimate_tokens
from .output import OutputPipeline
from .guard import _digest, run as guard_run
from .hook_runtime import (
    DEFAULT_KEEP_TAIL,
    DEFAULT_MIN_LINES,
    MIN_NET_TOKENS,
    HookConfig,
    HookRuntime,
    HookServices,
    cap_for as cap_for,
)
from .policy import user_nudge
from .runtime_config import settings_for
from .state import record_read, reset_session

DISABLE_ENV = "TOKEN_SAVER_DISABLED"


def _env_int(name: str, fallback: int) -> int:
    """Read an integer environment setting or return ``fallback``."""

    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _env_bool(name: str, fallback: bool = False) -> bool:
    """Read a conventional truthy environment setting."""

    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _passthrough() -> int:
    """Return the successful exit status that tells Claude to keep original data."""

    return 0


def _config_from_env(root: Path | None = None) -> HookConfig:
    """Resolve project configuration with environment-variable overrides."""

    settings = settings_for(root)
    return HookConfig(
        disabled=settings.disabled,
        delta_enabled=settings.delta,
        min_lines=settings.min_lines,
        keep_tail=settings.keep_tail,
        max_lines=settings.max_lines,
        min_net_tokens=MIN_NET_TOKENS,
    )


def _services() -> HookServices:
    """Compose concrete Token Saver services for the Claude adapter.

    Construction happens per top-level call so tests and embedders can replace
    module-level callables without hidden singleton state.
    """

    from .output_store import store_output as store_output_service

    return HookServices(
        guard=guard_run,
        output_pipeline=OutputPipeline(),
        apply_delta=apply_delta,
        store_output=store_output_service,
        user_nudge=user_nudge,
        reset_session=reset_session,
        record_read=record_read,
        digest=_digest,
        estimate_tokens=estimate_tokens,
    )


def _runtime(root: Path | None = None) -> HookRuntime:
    """Build the Claude runtime from project config plus environment overrides."""

    return HookRuntime(_services(), _config_from_env(root))


def _payload_root(payload: dict) -> Path:
    """Resolve the project root carried by one Claude hook payload."""

    raw = payload.get("cwd") or payload.get("cwd_path")
    return Path(str(raw)) if raw else Path.cwd()


def run_post(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude post-tool payload through the default runtime."""

    return _runtime(_payload_root(payload)).run_post(payload)


def run_session_start(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude session-start payload through the default runtime."""

    return _runtime(_payload_root(payload)).run_session_start(payload)


def run_user_prompt(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude user-prompt payload through the default runtime."""

    return _runtime(_payload_root(payload)).run_user_prompt(payload)


def run_post_read(payload: dict) -> None:
    """Record a Claude full-file read through the default runtime."""

    _runtime(_payload_root(payload)).run_post_read(payload)


def run(payload: dict) -> tuple[int, dict | None]:
    """Process one Claude hook payload through the default runtime."""

    return _runtime(_payload_root(payload)).run(payload)


def main(argv: list[str] | None = None) -> int:
    """Run the Claude hook JSON stdin/stdout adapter."""

    del argv
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return _passthrough()
    if not isinstance(payload, dict):
        return _passthrough()
    try:
        code, response = run(payload)
    except Exception as exc:
        print(f"token-saver hook error: {exc}", file=sys.stderr)
        return _passthrough()
    if response is not None:
        json.dump(response, sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

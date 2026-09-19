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
from .output_store import store_output
from .policy import user_nudge
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


def _config_from_env() -> HookConfig:
    """Translate Claude hook environment variables into runtime configuration."""

    max_lines_raw = os.environ.get("TOKEN_SAVER_MAX_LINES")
    max_lines: int | None = None
    if max_lines_raw is not None:
        try:
            max_lines = max(1, int(max_lines_raw))
        except ValueError:
            max_lines = None

    return HookConfig(
        disabled=_env_bool(DISABLE_ENV),
        delta_enabled=_env_bool("TOKEN_SAVER_DELTA"),
        min_lines=max(1, _env_int("TOKEN_SAVER_MIN_LINES", DEFAULT_MIN_LINES)),
        keep_tail=max(0, _env_int("TOKEN_SAVER_KEEP_TAIL", DEFAULT_KEEP_TAIL)),
        max_lines=max_lines,
        min_net_tokens=MIN_NET_TOKENS,
    )


def _services() -> HookServices:
    """Compose concrete Token Saver services for the Claude adapter.

    Construction happens per top-level call so tests and embedders can replace
    module-level callables without hidden singleton state.
    """

    return HookServices(
        guard=guard_run,
        output_pipeline=OutputPipeline(),
        apply_delta=apply_delta,
        store_output=store_output,
        user_nudge=user_nudge,
        reset_session=reset_session,
        record_read=record_read,
        digest=_digest,
        estimate_tokens=estimate_tokens,
    )


def _runtime() -> HookRuntime:
    """Build the default Claude runtime from current environment and services."""

    return HookRuntime(_services(), _config_from_env())


def run_post(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude post-tool payload through the default runtime."""

    return _runtime().run_post(payload)


def run_session_start(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude session-start payload through the default runtime."""

    return _runtime().run_session_start(payload)


def run_user_prompt(payload: dict) -> tuple[int, dict | None]:
    """Process a Claude user-prompt payload through the default runtime."""

    return _runtime().run_user_prompt(payload)


def run_post_read(payload: dict) -> None:
    """Record a Claude full-file read through the default runtime."""

    _runtime().run_post_read(payload)


def run(payload: dict) -> tuple[int, dict | None]:
    """Process one Claude hook payload through the default runtime."""

    return _runtime().run(payload)


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

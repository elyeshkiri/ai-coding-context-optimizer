"""Project-level runtime configuration with environment overrides."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .generation_policy import OUTPUT_TASK_OPTIONS
from .output_saver import OUTPUT_MODES

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

CONFIG_NAME = ".token-saver.toml"


@dataclass(frozen=True)
class RuntimeSettings:
    """Resolved Token Saver runtime settings for one project."""

    disabled: bool = False
    guard: bool = True
    read_max_lines: int = 220
    reread: bool = False
    allow: tuple[str, ...] = ()
    delta: bool = False
    min_lines: int = 40
    max_lines: int | None = None
    keep_tail: int = 15
    output_policy: bool = True
    output_mode: str = "normal"
    output_task: str = "auto"
    output_adaptive: bool = True
    output_min_tokens: int | None = None
    output_max_tokens: int | None = None
    output_calibration_file: str = ".token-saver.output-calibration.json"


def find_project_config(start: Path | None = None) -> Path | None:
    """Find the nearest project config by walking toward the filesystem root."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def _bool(value: object, fallback: bool) -> bool:
    """Normalize TOML booleans while preserving fallback for other values."""
    return value if isinstance(value, bool) else fallback


def _positive_int(value: object, fallback: int) -> int:
    """Normalize positive integer settings."""
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else fallback
    )


def _choice(value: object, fallback: str, choices: tuple[str, ...]) -> str:
    """Normalize a string choice while preserving fallback for invalid values."""
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().lower()
    return normalized if normalized in choices else fallback


def _string(value: object, fallback: str) -> str:
    """Normalize a non-empty string setting."""
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


def _optional_positive_int(
    value: object, fallback: int | None
) -> int | None:
    """Normalize an optional positive integer setting."""
    if value is None:
        return None
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else fallback
    )


def _load_file(start: Path | None = None) -> RuntimeSettings:
    """Load the nearest TOML config without environment overrides."""
    path = find_project_config(start)
    if path is None:
        return RuntimeSettings()
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Invalid Token Saver config: {path}") from exc
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Expected [hooks] table in Token Saver config: {path}")
    output = payload.get("output", {})
    if not isinstance(output, dict):
        raise ValueError(f"Expected [output] table in Token Saver config: {path}")
    allow = hooks.get("allow", [])
    allow_tuple = (
        tuple(item for item in allow if isinstance(item, str))
        if isinstance(allow, list)
        else ()
    )
    keep_tail = hooks.get("keep_tail", 15)
    if not isinstance(keep_tail, int) or isinstance(keep_tail, bool):
        keep_tail = 15
    return RuntimeSettings(
        disabled=_bool(hooks.get("disabled"), False),
        guard=_bool(hooks.get("guard"), True),
        read_max_lines=_positive_int(hooks.get("read_max_lines"), 220),
        reread=_bool(hooks.get("reread"), False),
        allow=allow_tuple,
        delta=_bool(hooks.get("delta"), False),
        min_lines=_positive_int(hooks.get("min_lines"), 40),
        max_lines=_optional_positive_int(hooks.get("max_lines"), None),
        keep_tail=max(0, keep_tail),
        output_policy=_bool(output.get("enabled"), True),
        output_mode=_choice(output.get("mode"), "normal", OUTPUT_MODES),
        output_task=_choice(output.get("task"), "auto", OUTPUT_TASK_OPTIONS),
        output_adaptive=_bool(output.get("adaptive"), True),
        output_min_tokens=_optional_positive_int(output.get("min_tokens"), None),
        output_max_tokens=_optional_positive_int(output.get("max_tokens"), None),
        output_calibration_file=_string(
            output.get("calibration_file"),
            ".token-saver.output-calibration.json",
        ),
    )


def _env_bool(name: str, fallback: bool) -> bool:
    """Read a conventional boolean environment override."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_string(name: str, fallback: str) -> str:
    """Read a non-empty string environment override."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    normalized = raw.strip()
    return normalized or fallback


def _env_choice(name: str, fallback: str, choices: tuple[str, ...]) -> str:
    """Read a normalized string-choice environment override."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    normalized = raw.strip().lower()
    return normalized if normalized in choices else fallback


def _env_int(
    name: str, fallback: int | None, *, minimum: int = 1
) -> int | None:
    """Read an integer environment override."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    try:
        return max(minimum, int(raw))
    except ValueError:
        return fallback


def settings_for(start: Path | None = None) -> RuntimeSettings:
    """Resolve project config with environment variables taking precedence."""
    base = _load_file(start)
    allow_raw = os.environ.get("TOKEN_SAVER_ALLOW")
    allow = (
        tuple(part for part in allow_raw.split(":") if part)
        if allow_raw is not None
        else base.allow
    )
    max_lines = _env_int("TOKEN_SAVER_MAX_LINES", base.max_lines)
    read_max_lines = _env_int(
        "TOKEN_SAVER_READ_MAX_LINES", base.read_max_lines
    )
    min_lines = _env_int("TOKEN_SAVER_MIN_LINES", base.min_lines)
    keep_tail = _env_int(
        "TOKEN_SAVER_KEEP_TAIL", base.keep_tail, minimum=0
    )
    return RuntimeSettings(
        disabled=_env_bool("TOKEN_SAVER_DISABLED", base.disabled),
        guard=_env_bool("TOKEN_SAVER_GUARD", base.guard),
        read_max_lines=int(read_max_lines or base.read_max_lines),
        reread=_env_bool("TOKEN_SAVER_REREAD", base.reread),
        allow=allow,
        delta=_env_bool("TOKEN_SAVER_DELTA", base.delta),
        min_lines=int(min_lines or base.min_lines),
        max_lines=max_lines,
        keep_tail=int(keep_tail if keep_tail is not None else base.keep_tail),
        output_policy=_env_bool("TOKEN_SAVER_OUTPUT_POLICY", base.output_policy),
        output_mode=_env_choice(
            "TOKEN_SAVER_OUTPUT_MODE", base.output_mode, OUTPUT_MODES
        ),
        output_task=_env_choice(
            "TOKEN_SAVER_OUTPUT_TASK", base.output_task, OUTPUT_TASK_OPTIONS
        ),
        output_adaptive=_env_bool(
            "TOKEN_SAVER_OUTPUT_ADAPTIVE", base.output_adaptive
        ),
        output_min_tokens=_env_int(
            "TOKEN_SAVER_OUTPUT_MIN_TOKENS", base.output_min_tokens
        ),
        output_max_tokens=_env_int(
            "TOKEN_SAVER_OUTPUT_MAX_TOKENS", base.output_max_tokens
        ),
        output_calibration_file=_env_string(
            "TOKEN_SAVER_OUTPUT_CALIBRATION_FILE",
            base.output_calibration_file,
        ),
    )

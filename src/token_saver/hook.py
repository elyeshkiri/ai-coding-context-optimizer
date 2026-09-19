"""Claude Code hook: guard large Reads, filter noisy tool output.

Claude Code sends a JSON object on stdin and reads JSON back.
PreToolUse can deny a tool call. PostToolUse can replace the result the
model sees via hookSpecificOutput.updatedToolOutput.

Reads are never rewritten after the fact: Edit matches on exact file
content. Large source Reads without a line range are denied up front and
the deny reason carries an outline plus ranges.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .estimate import estimate_tokens
from .filter_output import filter_command_output
from .delta_context import apply_delta
from .guard import run as guard_run
from .policy import user_nudge
from .state import record_read, reset_session

DEFAULT_MIN_LINES = 40
DEFAULT_KEEP_TAIL = 15
MIN_NET_TOKENS = 50
DISABLE_ENV = "TOKEN_SAVER_DISABLED"

# Bash logs only. Grep/WebFetch hits often sit in the middle; clipping them
# causes extra tool calls that cost more than the filter saved.
FILTERABLE = {"Bash"}


def cap_for(n_lines: int) -> int:
    """How many lines to keep, given how many came in."""
    if n_lines >= 1000:
        return 90
    if n_lines >= 300:
        return 60
    return 30


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _passthrough() -> int:
    return 0


def _disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _response_text(payload: dict) -> str | None:
    response = payload.get("tool_response")
    if isinstance(response, str) and response.strip():
        return response
    if isinstance(response, dict):
        for key in ("output", "stdout", "content", "result"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _is_filterable(tool_name: str) -> bool:
    return tool_name in FILTERABLE


def _exit_code(response: dict) -> int | None:
    for key in ("exit_code", "exitCode", "code"):
        value = response.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _delta_enabled() -> bool:
    return os.environ.get("TOKEN_SAVER_DELTA", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def run_post(payload: dict) -> tuple[int, dict | None]:
    tool = payload.get("tool_name") or ""
    if tool == "Read" or tool == "Edit":
        return 0, None
    if not _is_filterable(str(tool)):
        return 0, None

    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return 0, None
    if response.get("isImage") or response.get("interrupted"):
        return 0, None
    if not isinstance(response.get("stdout"), str) or not isinstance(response.get("stderr"), str):
        return 0, None
    # Fail open for unsupported shapes; never discard structured content.
    if not isinstance(response.get("interrupted"), bool) or not isinstance(response.get("isImage"), bool):
        return 0, None
    from .output_store import store_output
    min_lines = max(1, _env_int("TOKEN_SAVER_MIN_LINES", DEFAULT_MIN_LINES))
    keep_tail = max(0, _env_int("TOKEN_SAVER_KEEP_TAIL", DEFAULT_KEEP_TAIL))
    command = str((payload.get("tool_input") or {}).get("command", ""))
    replacement = dict(response)
    # Keep stderr intact: it often contains the only diagnostic evidence.
    original = response["stdout"]
    n_lines = len(original.splitlines())
    if n_lines < min_lines:
        return 0, None
    replacement["stdout"] = filter_command_output(
        original, command=command,
        max_lines=max(1, _env_int("TOKEN_SAVER_MAX_LINES", cap_for(n_lines))),
        keep_tail=keep_tail,
        exit_code=_exit_code(response),
    )
    if _delta_enabled():
        replacement["stdout"], _delta_meta = apply_delta(
            _cwd(payload),
            command,
            original,
            replacement["stdout"],
            session_id=payload.get("session_id"),
        )
    note = ("\n[token-saver: filtered output; original saved. "
            "Retrieve: token-saver output {id} --stream stdout --offset 1 --limit 80]\n")
    candidate = replacement["stdout"] + note.format(id="0" * 32)
    if estimate_tokens(original) - estimate_tokens(candidate) < MIN_NET_TOKENS:
        return 0, None
    if len(candidate.encode()) >= len(original.encode()):
        return 0, None
    output_id = store_output(response)  # failure must leave the original output in place
    replacement["stdout"] += note.format(id=output_id)
    return 0, {"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "updatedToolOutput": replacement,
    }}


def _cwd(payload: dict) -> Path:
    raw = payload.get("cwd") or payload.get("cwd_path") or "."
    return Path(str(raw))


def run_session_start(payload: dict) -> tuple[int, dict | None]:
    """Reset per-session state. Does not inject model context."""
    root = _cwd(payload)
    source = str(payload.get("source") or "").lower()
    new_convo = source in {"", "startup", "clear", "compact"}
    reset_session(root, reads=new_convo, reminder=True, session_id=payload.get("session_id"))
    return 0, None


def run_user_prompt(payload: dict) -> tuple[int, dict | None]:
    root = _cwd(payload)
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
    note = user_nudge(root, prompt)
    return (0, {"systemMessage": note}) if note else (0, None)


def run_post_read(payload: dict) -> None:
    """Remember a full-file Read. Ranged reads must not mark the whole file seen."""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return
    if any(k in tool_input for k in ("offset", "limit", "start_line", "end_line")):
        return
    raw = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filePath")
    if not raw:
        return
    path = Path(str(raw))
    if not path.is_absolute(): path = _cwd(payload) / path
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    response = payload.get("tool_response")
    info = response.get("file") if isinstance(response, dict) else None
    if not isinstance(info, dict) or info.get("content") != text:
        return
    from .guard import _digest
    record_read(_cwd(payload), path, _digest(text), session_id=payload.get("session_id"))


def run(payload: dict) -> tuple[int, dict | None]:
    if _disabled():
        return 0, None
    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    if event == "SessionStart":
        return run_session_start(payload)
    if event == "UserPromptSubmit":
        return run_user_prompt(payload)
    if event == "PreToolUse" or (
        not event and payload.get("tool_name") == "Read" and "tool_response" not in payload
    ):
        return guard_run(payload)
    if event == "PostToolUse" and payload.get("tool_name") == "Read":
        run_post_read(payload)
        return 0, None
    return run_post(payload)


def main(argv: list[str] | None = None) -> int:
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

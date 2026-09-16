"""PreToolUse guard: stop full-file reads of large source before they hit context.

Rewriting a Read *result* into an outline is harmful — Edit matches exact
bytes — so this hook never touches PostToolUse Read. It intercepts the
*request*: a Read of a large source file with no offset/limit is denied and
replaced with an outline plus the ranges to ask for.

Disable with TOKEN_SAVER_GUARD=0.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path

from .estimate import estimate_tokens
from .skeleton import CODE_SUFFIXES, skeletonize
from .state import seen_read

DEFAULT_READ_MAX_LINES = 220
OUTLINE_PREVIEW_TOKENS = 900
ALLOW_NAMES = {
    "package.json",
    "tsconfig.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
}


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _guard_enabled() -> bool:
    raw = os.environ.get("TOKEN_SAVER_GUARD", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _read_path(tool_input: dict) -> Path | None:
    raw = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filePath")
    if not raw or not isinstance(raw, str):
        return None
    return Path(raw)


def _has_range(tool_input: dict) -> bool:
    """True when the Read asks for a window, not the whole file.

    `offset: 0` alone is still a full read. `offset: 0, limit: N` is a window.
    """
    def _num(key: str) -> int | None:
        raw = tool_input.get(key)
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    maximum = max(1, _env_int("TOKEN_SAVER_READ_MAX_LINES", DEFAULT_READ_MAX_LINES))
    limit = _num("limit")
    if limit is not None:
        return 0 < limit <= maximum
    end = _num("end_line")
    start = _num("start_line") or _num("offset") or 1
    return end is not None and 0 < end - start + 1 <= maximum


def _is_source(path: Path) -> bool:
    return path.suffix.lower() in CODE_SUFFIXES and path.suffix.lower() not in {".md", ".markdown"}


def _allowed(path: Path) -> bool:
    if path.name in ALLOW_NAMES or path.name.endswith(".d.ts"):
        return True
    raw = os.environ.get("TOKEN_SAVER_ALLOW", "")
    if not raw.strip():
        return False
    name = path.name
    full = str(path)
    return any(fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(full, pat) for pat in raw.split(":") if pat)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def decide_read(tool_input: dict, cwd: Path | None = None, session_id: str | None = None) -> dict | None:
    """Return a deny payload, or None to allow the Read through."""
    if not _guard_enabled():
        return None
    path = _read_path(tool_input)
    if path is not None and not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    if path is None or not path.is_file():
        return None
    if _allowed(path):
        return None
    if not _is_source(path):
        return None
    if _has_range(tool_input):
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    root = (cwd or Path.cwd()).resolve()
    digest = _digest(text)
    n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    max_lines = _env_int("TOKEN_SAVER_READ_MAX_LINES", DEFAULT_READ_MAX_LINES)
    reread_on = os.environ.get("TOKEN_SAVER_REREAD", "0").strip().lower() in {
        "1", "true", "on", "yes",
    }
    if reread_on and n_lines > max_lines and seen_read(root, path, digest, session_id):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"token-saver: {path} is unchanged from an earlier Read this session "
                    f"(digest {digest}). Use the earlier content or a line range."
                ),
            }
        }
    if n_lines <= max_lines:
        return None

    outlined = skeletonize(text, path.suffix, line_numbers=True)
    # cap the deny-reason so the hook message itself does not become the dump
    lines = outlined.splitlines()
    preview: list[str] = []
    used = 0
    for ln in lines:
        cost = estimate_tokens(ln + "\n", path.suffix)
        if used + cost > OUTLINE_PREVIEW_TOKENS:
            preview.append(f"… ({len(lines) - len(preview)} outline lines omitted)")
            break
        preview.append(ln)
        used += cost
    preview_text = "\n".join(preview)
    reason = (
        f"token-saver blocked a full Read of {path} ({n_lines} lines, "
        f"~{estimate_tokens(text, path.suffix)} tokens). "
        f"Edit needs exact bytes, so use Read with offset+limit on the gutter "
        f"ranges below instead of ingesting the whole file.\n\n"
        f"{preview_text}"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def run(payload: dict) -> tuple[int, dict | None]:
    if payload.get("tool_name") != "Read":
        return 0, None
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0, None
    raw_cwd = payload.get("cwd") or payload.get("cwd_path")
    cwd = Path(str(raw_cwd)) if raw_cwd else Path.cwd()
    decision = decide_read(tool_input, cwd=cwd, session_id=payload.get("session_id"))
    return 0, decision

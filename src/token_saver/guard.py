"""PreToolUse guard: stop full-file reads of large source before they hit context.

Rewriting a Read *result* into an outline is harmful — Edit matches exact
bytes — so this hook never touches PostToolUse Read. It intercepts the
*request*: a Read of a large source file with no offset/limit is denied and
replaced with an outline plus the ranges to ask for.

A whole-file ``cat`` through Bash is the same dump by another route, so a plain
``cat <large source file>`` is denied the same way. Only a lone ``cat`` command
is inspected; pipes, redirects, chains and globs are left alone.

Disable with TOKEN_SAVER_GUARD=0.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import shlex
from pathlib import Path

from .cache_economics import assess_context_rewrite
from .efficiency.store import append_event
from .estimate import estimate_tokens
from .knowledge import FindingStore
from .skeleton import CODE_SUFFIXES, skeletonize
from .runtime_config import settings_for
from .state import seen_read

OUTLINE_PREVIEW_TOKENS = 900
KNOWLEDGE_PREVIEW_TOKENS = 500
KNOWLEDGE_MIN_NET_TOKENS = 80
ALLOW_NAMES = {
    "package.json",
    "tsconfig.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
}


def _guard_enabled(cwd: Path | None = None) -> bool:
    """Return whether the source-read guard is enabled for this project."""
    return settings_for(cwd).guard


def _read_path(tool_input: dict) -> Path | None:
    """Read path."""
    raw = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filePath")
    if not raw or not isinstance(raw, str):
        return None
    return Path(raw)


def _has_range(tool_input: dict, cwd: Path | None = None) -> bool:
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

    maximum = settings_for(cwd).read_max_lines
    limit = _num("limit")
    if limit is not None:
        return 0 < limit <= maximum
    end = _num("end_line")
    start = _num("start_line") or _num("offset") or 1
    return end is not None and 0 < end - start + 1 <= maximum


def _is_source(path: Path) -> bool:
    """Return whether source."""
    return path.suffix.lower() in CODE_SUFFIXES and path.suffix.lower() not in {".md", ".markdown"}


def _allowed(path: Path, cwd: Path | None = None) -> bool:
    """Return whether a source path is explicitly exempt from guarding."""
    if path.name in ALLOW_NAMES or path.name.endswith(".d.ts"):
        return True
    patterns = settings_for(cwd).allow
    if not patterns:
        return False
    name = path.name
    full = str(path)
    relative = ""
    try:
        relative = str(path.resolve().relative_to((cwd or Path.cwd()).resolve()))
    except ValueError:
        pass
    return any(
        fnmatch.fnmatch(name, pattern)
        or fnmatch.fnmatch(full, pattern)
        or bool(relative and fnmatch.fnmatch(relative, pattern))
        for pattern in patterns
    )


def _digest(text: str) -> str:
    """Handle digest."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _bounded_text(value: object, limit: int) -> str:
    """Return one compact single-line field for a guard explanation."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _knowledge_reason(root: Path, path: Path, findings: list[dict]) -> str:
    """Render current verified findings as a bounded read-avoidance replacement."""
    lines = [
        (
            "token-saver avoided a full Read because verified project knowledge "
            f"is still anchored to unchanged source: {path}."
        )
    ]
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = ""
    for item in findings[:3]:
        anchors = item.get("anchors")
        anchors = anchors if isinstance(anchors, list) else []
        symbols = sorted(
            {
                str(anchor.get("symbol"))
                for anchor in anchors
                if isinstance(anchor, dict)
                and anchor.get("path")
                and str(anchor["path"]) == relative
                and anchor.get("symbol")
            }
        )
        suffix = f" [symbols: {', '.join(symbols)}]" if symbols else ""
        lines.append(
            "- "
            + _bounded_text(item.get("claim"), 240)
            + suffix
            + " Evidence: "
            + _bounded_text(item.get("evidence"), 280)
            + " Applies when: "
            + _bounded_text(item.get("applicability"), 180)
        )
    lines.append(
        "If exact implementation bytes are required for an edit or verification, "
        "request a bounded Read with offset+limit instead of the whole file."
    )
    rendered: list[str] = []
    used = 0
    for line in lines:
        cost = estimate_tokens(line + "\n", ".txt")
        if used + cost > KNOWLEDGE_PREVIEW_TOKENS:
            break
        rendered.append(line)
        used += cost
    return "\n".join(rendered)


def _knowledge_read_decision(
    root: Path,
    path: Path,
    text: str,
    settings,
) -> dict | None:
    """Return a read-avoidance decision when current verified knowledge is cheaper."""
    if not (
        settings.efficiency_enabled
        and settings.knowledge_read_avoidance
    ):
        return None
    try:
        findings = FindingStore(root).for_path(path, verified_only=True, limit=3)
    except ValueError:
        return None
    if not findings:
        return None

    reason = _knowledge_reason(root, path, findings)
    original_tokens = estimate_tokens(text, path.suffix)
    replacement_tokens = estimate_tokens(reason, ".txt")
    net_tokens = original_tokens - replacement_tokens
    if net_tokens < KNOWLEDGE_MIN_NET_TOKENS:
        return None

    economics = None
    if settings.cache_economics:
        economics = assess_context_rewrite(
            original_frontier_tokens=original_tokens,
            replacement_frontier_tokens=replacement_tokens,
            cached_prefix_tokens=0,
            invalidates_cached_prefix=False,
            expected_reuses=settings.cache_expected_reuses,
            cache_write_factor=settings.cache_write_factor,
            cache_read_factor=settings.cache_read_factor,
            min_relative_savings=settings.cache_min_relative_savings,
        )
        if not economics.accepted:
            return None

    event = {
        "kind": "saving",
        "feature": "knowledge_read_avoidance",
        "estimated_tokens_saved": net_tokens,
        "finding_count": len(findings),
    }
    if economics is not None:
        event["cache_economics"] = {
            "original_cost": economics.original_cost,
            "replacement_cost": economics.replacement_cost,
            "relative_savings": economics.relative_savings,
            "expected_reuses": economics.expected_reuses,
        }
    append_event(root, event)
    return _deny(reason)


def decide_read(tool_input: dict, cwd: Path | None = None, session_id: str | None = None) -> dict | None:
    """Return a deny payload, or None to allow the Read through."""
    base = cwd or Path.cwd()
    settings = settings_for(base)
    if not settings.guard:
        return None
    path = _read_path(tool_input)
    if path is not None and not path.is_absolute():
        path = base / path
    if path is None or not path.is_file():
        return None
    if _allowed(path, base):
        return None
    if not _is_source(path):
        return None
    if _has_range(tool_input, base):
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    root = (cwd or Path.cwd()).resolve()
    digest = _digest(text)
    n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    max_lines = settings.read_max_lines
    knowledge_decision = _knowledge_read_decision(root, path, text, settings)
    if knowledge_decision is not None:
        return knowledge_decision

    reread_on = settings.reread or (
        settings.efficiency_enabled and settings.cross_turn_dedup
    )
    if reread_on and seen_read(root, path, digest, session_id):
        append_event(
            root,
            {
                "kind": "saving",
                "feature": "unchanged_read_block",
                "estimated_tokens_saved": estimate_tokens(text, path.suffix),
            },
        )
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

    return _deny(_outline_reason(path, text, n_lines, "a full Read"))


def _outline_reason(path: Path, text: str, n_lines: int, action: str) -> str:
    """Handle outline reason."""
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
    return (
        f"token-saver blocked {action} of {path} ({n_lines} lines, "
        f"~{estimate_tokens(text, path.suffix)} tokens). "
        f"Edit needs exact bytes, so use Read with offset+limit on the gutter "
        f"ranges below instead of ingesting the whole file.\n\n"
        f"{preview_text}"
    )


def _deny(reason: str) -> dict:
    """Handle deny."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


_CAT_FLAGS = re.compile(r"^-[nbsAETv]+$")
_SHELL_SYNTAX = set("|&;<>()`$*?[]{}\\")
MAX_BLOCKED_FILES = 3


def _cat_paths(command: str) -> list[str] | None:
    """File arguments of a lone ``cat`` command, or None for anything else."""
    cmd = re.sub(r"\s+2>&1\s*$", "", command.strip())
    if not re.match(r"cat(\s|$)", cmd):
        return None
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    paths: list[str] = []
    for token in tokens[1:]:
        if _CAT_FLAGS.match(token):
            continue
        if token.startswith("-") or _SHELL_SYNTAX & set(token):
            return None
        paths.append(token)
    return paths or None


def decide_bash(command: str, cwd: Path | None = None) -> dict | None:
    """Deny ``cat <large source file>``; None lets the command run."""
    base = cwd or Path.cwd()
    settings = settings_for(base)
    if not settings.guard:
        return None
    paths = _cat_paths(command)
    if not paths:
        return None
    max_lines = settings.read_max_lines
    reasons: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        if not path.is_file() or _allowed(path, base) or not _is_source(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        if n_lines > max_lines:
            reasons.append(_outline_reason(path, text, n_lines, "`cat`"))
        if len(reasons) == MAX_BLOCKED_FILES:
            break
    return _deny("\n\n".join(reasons)) if reasons else None


def run(payload: dict) -> tuple[int, dict | None]:
    """Run the requested value."""
    tool = payload.get("tool_name")
    if tool not in {"Read", "Bash"}:
        return 0, None
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0, None
    raw_cwd = payload.get("cwd") or payload.get("cwd_path")
    cwd = Path(str(raw_cwd)) if raw_cwd else Path.cwd()
    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return 0, None
        return 0, decide_bash(command, cwd=cwd)
    decision = decide_read(tool_input, cwd=cwd, session_id=payload.get("session_id"))
    return 0, decision

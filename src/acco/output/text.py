"""Shared text normalization and preservation primitives for output processors."""

from __future__ import annotations

import json
import re

from ..fastpath import (
    collapse_repeated_lines as _fast_collapse_repeated_lines,
    critical_lines as _fast_critical_lines,
    strip_ansi as _fast_strip_ansi,
)

ERROR_HINTS = re.compile(
    r"(error|exception|fail|failed|fatal|panic|traceback|assert|expected|received)",
    re.I,
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BLANK_RUN = re.compile(r"\n{3,}")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{96,}\b")
_CRITICAL = re.compile(
    r"(?i)(Traceback|AssertionError|\b(?:ERROR|FAILED|FATAL|PANIC)\b|Caused by:|"
    r"(?:^|\s)[\w./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|cs|rb|php):\d+)"
)
MAX_ERROR_LINES = 40
MAX_RECOVERED_LINES = 20


def ensure_newline(text: str) -> str:
    """Return ``text`` with a trailing newline when non-empty."""
    if not text or text.endswith("\n"):
        return text
    return text + "\n"


def strip_ansi(text: str) -> str:
    """Remove ANSI terminal escape sequences from ``text``."""
    return _fast_strip_ansi(text)


def collapse_repeated_lines(text: str, minimum: int = 3) -> str:
    """Collapse consecutive identical non-empty lines when doing so saves bytes."""
    return _fast_collapse_repeated_lines(text, minimum)


def preprocess(text: str) -> str:
    """Normalize safe boilerplate before format-specific compression."""
    if not text:
        return text
    out = strip_ansi(text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _BLANK_RUN.sub("\n\n", out)
    out = _HEX_BLOB.sub(
        lambda match: match.group(0)[:12] + f"…({len(match.group(0))} hex)",
        out,
    )
    stripped = out.strip()
    if stripped[:1] in "{[" and stripped[-1:] in "]}":
        try:
            packed = json.dumps(
                json.loads(stripped), separators=(",", ":"), ensure_ascii=False
            )
            if len(packed) + 1 < len(out):
                out = packed + "\n"
                return out if len(out) <= len(text) else text
        except (ValueError, TypeError):
            pass
    out = collapse_repeated_lines(out)
    return out if len(out) <= len(text) else text


def filter_text(
    text: str,
    max_lines: int = 80,
    keep_tail: int = 20,
    *,
    prepared: bool = False,
) -> str:
    """Keep a bounded head/error/tail view without ever growing the input."""
    if not prepared:
        text = preprocess(text)
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return ensure_newline(text)

    keep_tail = max(0, min(keep_tail, max_lines - 1, len(lines) - 1))
    important_count = sum(1 for line in lines if ERROR_HINTS.search(line))
    head_n = max(10, max_lines - keep_tail - min(important_count, 30))
    head_n = max(0, min(head_n, len(lines) - keep_tail))
    tail_start = len(lines) - keep_tail
    shown = set(range(head_n)) | set(range(tail_start, len(lines)))

    extra: list[str] = []
    seen: set[str] = set()
    for i in range(head_n, tail_start):
        line = lines[i]
        if not ERROR_HINTS.search(line):
            continue
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        extra.append(line)
        shown.add(i)
        if len(extra) >= MAX_ERROR_LINES:
            break

    omitted = len(lines) - len(shown)
    if omitted <= 0:
        return ensure_newline(text)
    blocks = [
        f"[filtered: {len(lines)} lines → showing head/errors/tail; {omitted} omitted]",
        *lines[:head_n],
    ]
    if extra:
        blocks.append("--- matching errors ---")
        blocks.extend(extra)
    if keep_tail:
        blocks.append("--- tail ---")
        blocks.extend(lines[tail_start:])
    out = "\n".join(blocks) + "\n"
    return out if len(out) < len(text) else ensure_newline(text)


def critical_lines(text: str) -> list[str]:
    """Return bounded, unique diagnostic lines that must survive compression."""
    return _fast_critical_lines(text, MAX_RECOVERED_LINES)


def recover_critical_lines(original: str, candidate: str) -> tuple[str, tuple[str, ...]]:
    """Restore omitted critical diagnostics when the restored result is still smaller."""
    present = {line.strip() for line in candidate.splitlines() if line.strip()}
    missing = tuple(
        line for line in critical_lines(original) if line.strip() not in present
    )
    if not missing:
        return candidate, ()
    recovered = (
        candidate.rstrip("\n")
        + "\n\n[token-saver: recovered critical diagnostics]\n"
        + "\n".join(missing)
        + "\n"
    )
    if len(recovered.encode()) >= len(original.encode()):
        return original, ()
    return recovered, missing

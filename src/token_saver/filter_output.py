"""Compress noisy tool/command output before it hits the model."""

from __future__ import annotations

import json
import re

ERROR_HINTS = re.compile(
    r"(error|exception|fail|failed|fatal|panic|traceback|assert|expected|received)",
    re.I,
)

MAX_ERROR_LINES = 40

# Command-specific keepers. A pytest dump is not a generic log: the failures
# are the payload. Matching is on the command string when the hook has one.
_PYTEST = re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b", re.I)
_JEST = re.compile(r"\b(jest|vitest|npm\s+test|pnpm\s+test|yarn\s+test)\b", re.I)
_GIT_LOG = re.compile(r"\bgit\s+log\b", re.I)
_NPM_INSTALL = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(i|install|ci)\b", re.I)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BLANK_RUN = re.compile(r"\n{3,}")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{96,}\b")


def _ensure_nl(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    return text + "\n"


def _collapse_repeated_lines(text: str, minimum: int = 3) -> str:
    """Collapse consecutive duplicate log lines while preserving their count."""
    lines = text.splitlines()
    if len(lines) < minimum:
        return text
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j] == line:
            j += 1
        count = j - i
        if line.strip() and count >= minimum:
            out.append(line)
            out.append(f"[token-saver: previous line repeated {count - 1} more times]")
        else:
            out.extend(lines[i:j])
        i = j
    candidate = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    return candidate if len(candidate) < len(text) else text


def preprocess(text: str) -> str:
    """Cheap conservative passes that shrink successful logs without hiding errors."""
    if not text:
        return text
    out = _ANSI.sub("", text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _BLANK_RUN.sub("\n\n", out)
    out = _HEX_BLOB.sub(lambda m: m.group(0)[:12] + f"…({len(m.group(0))} hex)", out)

    # Valid JSON is information-dense when compacted and should not be modified
    # by the line-deduper below.
    stripped = out.strip()
    if stripped[:1] in "{[" and stripped[-1:] in "}]":
        try:
            packed = json.dumps(json.loads(stripped), separators=(",", ":"), ensure_ascii=False)
            if len(packed) + 1 < len(out):
                out = packed + "\n"
                return out if len(out) <= len(text) else text
        except (ValueError, TypeError):
            pass

    out = _collapse_repeated_lines(out)
    return out if len(out) <= len(text) else text


def filter_text(text: str, max_lines: int = 80, keep_tail: int = 20, *, prepared: bool = False) -> str:
    """Shrink `text` to roughly `max_lines`, keeping head, error lines, and tail.

    Guarantees the result is never longer than the input: if the filtered form
    would not be smaller, the original is returned unchanged.
    """
    if not prepared:
        text = preprocess(text)
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return _ensure_nl(text)

    # keep_tail must leave room for at least one head line
    keep_tail = max(0, min(keep_tail, max_lines - 1, len(lines) - 1))

    important_count = sum(1 for ln in lines if ERROR_HINTS.search(ln))
    head_n = max(10, max_lines - keep_tail - min(important_count, 30))
    # never let head and tail overlap
    head_n = max(0, min(head_n, len(lines) - keep_tail))

    tail_start = len(lines) - keep_tail
    shown = set(range(head_n)) | set(range(tail_start, len(lines)))

    # error lines from the omitted middle, first occurrence only
    extra: list[str] = []
    seen: set[str] = set()
    for i in range(head_n, tail_start):
        ln = lines[i]
        if not ERROR_HINTS.search(ln):
            continue
        key = ln.strip()
        if key in seen:
            continue
        seen.add(key)
        extra.append(ln)
        shown.add(i)
        if len(extra) >= MAX_ERROR_LINES:
            break

    omitted = len(lines) - len(shown)
    if omitted <= 0:
        return _ensure_nl(text)

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
    # a "filter" that grows its input is worse than no filter
    return out if len(out) < len(text) else _ensure_nl(text)


_FAIL_BLOCK = re.compile(
    r"^=+ FAILURES =+[\s\S]*?(?=^=+ (?:short test summary|warnings summary)|\Z)",
    re.M | re.I,
)
_SHORT_SUMMARY = re.compile(
    r"^=+ short test summary info =+[\s\S]*?(?=^=+ |\Z)",
    re.M | re.I,
)
_LAST_COUNTS = re.compile(r"=+ .*\d+ (passed|failed|error).* =+\s*$", re.I | re.M)


def _pytest_slice(text: str) -> str | None:
    """Keep failures + short summary + final counts. Drop collection chatter."""
    parts: list[str] = []
    fail = _FAIL_BLOCK.search(text)
    if fail:
        parts.append(fail.group(0).strip())
    summary = _SHORT_SUMMARY.search(text)
    if summary:
        parts.append(summary.group(0).strip())
    counts = list(_LAST_COUNTS.finditer(text))
    if counts:
        parts.append(counts[-1].group(0).strip())
    if not parts:
        return None
    body = "\n\n".join(parts)
    header = f"[filtered pytest: {len(text.splitlines())} lines → failures/summary]\n"
    out = header + body + "\n"
    return out if len(out) < len(text) else None


def _keep_matching(text: str, pattern: re.Pattern[str], limit: int, label: str) -> str | None:
    lines = text.splitlines()
    kept = [ln for ln in lines if pattern.search(ln)]
    if not kept:
        return None
    kept = kept[:limit]
    omitted = len(lines) - len(kept)
    if omitted <= 0:
        return None
    out = (
        f"[filtered {label}: {len(lines)} lines → {len(kept)} kept, {omitted} omitted]\n"
        + "\n".join(kept)
        + "\n"
    )
    return out if len(out) < len(text) else None


def filter_command_output(
    text: str,
    command: str = "",
    max_lines: int = 80,
    keep_tail: int = 20,
) -> str:
    """Filter with a command-specific pass first, then the generic clipper."""
    # Failures need surrounding stack frames, test names and source excerpts.
    # Prefer no compression to a misleading partial diagnostic.
    if ERROR_HINTS.search(_ANSI.sub("", text)):
        if _PYTEST.search(command) and _FAIL_BLOCK.search(text):
            return _pytest_slice(text) or text
        return text
    text = preprocess(text)
    if command:
        if _PYTEST.search(command):
            specialized = _pytest_slice(text)
            if specialized:
                return specialized
        if _JEST.search(command):
            specialized = _keep_matching(
                text,
                re.compile(r"(FAIL|✕|×|Error|Expected|Received|Tests:|Test Suites:)", re.I),
                limit=80,
                label="test",
            )
            if specialized:
                return specialized
        if _GIT_LOG.search(command):
            lines = text.splitlines()
            if len(lines) > 40:
                clipped = "\n".join(lines[:25]) + f"\n[filtered git log: {len(lines) - 25} commits omitted]\n"
                if len(clipped) < len(text):
                    return clipped
        if _NPM_INSTALL.search(command):
            specialized = _keep_matching(
                text,
                re.compile(r"(ERR!|error|warn|added \d+|removed \d+|audited)", re.I),
                limit=40,
                label="install",
            )
            if specialized:
                return specialized
    return filter_text(text, max_lines=max_lines, keep_tail=keep_tail, prepared=True)

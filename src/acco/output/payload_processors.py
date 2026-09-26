"""Content-type-aware fallback processors for unknown command output."""

from __future__ import annotations

import json
import re

from ..browser_context import compress_browser_payload, detect_browser_payload_kind
from .text import ensure_newline, preprocess

_LOG_LINE = re.compile(
    r"(?i)^(?:\[?\d{4}-\d{2}-\d{2}[T ][^\]]*\]?\s*)?"
    r"(?:TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b"
)
_IMPORTANT_LOG = re.compile(
    r"(?i)\b(ERROR|FATAL|CRITICAL|WARN(?:ING)?|exception|traceback|panic|failed)\b"
)
_DIFF_HEADER = re.compile(r"^(?:diff --git |index |--- |\+\+\+ |@@ )")


class _PayloadOnly:
    """Base class for processors selected by payload shape rather than command."""

    priority = 800
    handles_failure = False

    def matches(self, command: str) -> bool:
        """Decline command-name matching so payload routing can decide."""
        del command
        return False


class BrowserPagePayloadProcessor(_PayloadOnly):
    """Focus HTML/AX page dumps even when the producing command is unknown."""

    name = "payload-page"
    priority = 805
    handles_failure = True

    def matches_payload(self, text: str) -> bool:
        """Return whether text looks like a substantial HTML or AX page dump."""
        if len(text) < 2000:
            return False
        return detect_browser_payload_kind(text) in {"html", "ax"}

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Focus structural/actionable page evidence under the line budget."""
        del command, failed, keep_tail
        result = compress_browser_payload(
            text,
            max_lines=max(20, max_lines),
            recovery=None,
            format_hint="auto",
        )
        return result.text if result.changed else text


class JsonPayloadProcessor(_PayloadOnly):
    """Compact very large JSON arrays while preserving object/scalar fields."""

    name = "payload-json"
    priority = 810

    def matches_payload(self, text: str) -> bool:
        """Return whether text is a large valid JSON payload."""
        stripped = text.lstrip()
        if not stripped.startswith(("{", "[")):
            return False
        try:
            json.loads(text)
        except (ValueError, TypeError):
            return False
        return len(text.splitlines()) > 20 or len(text) > 5000

    def _compact(self, value, depth: int = 0):
        """Recursively bound large arrays while preserving JSON structure."""
        if depth >= 5:
            return value
        if isinstance(value, list):
            if len(value) <= 12:
                return [self._compact(item, depth + 1) for item in value]
            return [
                *[self._compact(item, depth + 1) for item in value[:6]],
                {"_acco_omitted_items": len(value) - 10},
                *[self._compact(item, depth + 1) for item in value[-4:]],
            ]
        if isinstance(value, dict):
            return {
                str(key): self._compact(item, depth + 1)
                for key, item in value.items()
            }
        return value

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Serialize a bounded structural JSON representation."""
        del command, failed, max_lines, keep_tail
        value = json.loads(text)
        candidate = json.dumps(
            self._compact(value),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return ensure_newline(candidate) if len(candidate) < len(text) else text


class DiffPayloadProcessor(_PayloadOnly):
    """Remove unchanged diff context while preserving every changed line."""

    name = "payload-diff"
    priority = 820

    def matches_payload(self, text: str) -> bool:
        """Return whether text is a substantial unified Git diff."""
        lines = text.splitlines()
        return (
            len(lines) > 30
            and any(line.startswith("diff --git ") for line in lines)
            and any(line.startswith("@@ ") for line in lines)
        )

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep diff structure and every changed line while dropping context."""
        del command, failed, max_lines, keep_tail
        out: list[str] = []
        omitted = 0

        def flush() -> None:
            """Emit one marker for the accumulated unchanged context."""
            nonlocal omitted
            if omitted:
                out.append(f" ... {omitted} unchanged diff context line(s) omitted ...")
                omitted = 0

        for line in text.splitlines():
            changed = (
                _DIFF_HEADER.match(line)
                or (line.startswith("+") and not line.startswith("+++"))
                or (line.startswith("-") and not line.startswith("---"))
                or line.startswith("\\ No newline")
            )
            if changed:
                flush()
                out.append(line)
            else:
                omitted += 1
        flush()
        candidate = "\n".join(out) + "\n"
        return candidate if len(candidate) < len(text) else text


class LogPayloadProcessor(_PayloadOnly):
    """Bound generic timestamped/leveled logs while retaining diagnostics."""

    name = "payload-log"
    priority = 830
    handles_failure = True

    def matches_payload(self, text: str) -> bool:
        """Return whether text resembles a large leveled log stream."""
        lines = text.splitlines()
        if len(lines) < 80:
            return False
        sample = lines[: min(100, len(lines))]
        matches = sum(bool(_LOG_LINE.search(line)) for line in sample)
        return matches >= max(10, len(sample) // 3)

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep diagnostics plus bounded head and tail log evidence."""
        del command, failed
        lines = preprocess(text).splitlines()
        important = [
            line for line in lines
            if _IMPORTANT_LOG.search(line)
        ]
        head = lines[:5]
        tail = lines[-max(10, keep_tail):]
        keep = max(20, max_lines)
        merged: list[str] = []
        for line in [*head, *important[:keep], *tail]:
            if line not in merged:
                merged.append(line)
        if len(merged) >= len(lines):
            return text
        return (
            f"[filtered generic log: {len(lines)} lines -> {len(merged)} kept]\n"
            + "\n".join(merged)
            + "\n"
        )


class TablePayloadProcessor(_PayloadOnly):
    """Bound large Markdown tables while retaining header and both edges."""

    name = "payload-table"
    priority = 840

    def matches_payload(self, text: str) -> bool:
        """Return whether text is predominantly a large Markdown table."""
        lines = text.splitlines()
        if len(lines) < 40:
            return False
        table_lines = sum(line.count("|") >= 2 for line in lines)
        return table_lines >= len(lines) * 0.8

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep table headers and bounded leading/trailing rows."""
        del command, failed
        lines = text.splitlines()
        budget = max(12, min(max_lines, 40))
        if len(lines) <= budget:
            return text
        head_count = max(4, budget // 2)
        tail_count = max(3, min(keep_tail, budget - head_count - 1))
        omitted = len(lines) - head_count - tail_count
        candidate = [
            *lines[:head_count],
            f"| ... {omitted} row(s) omitted; recover original for full table ... |",
            *lines[-tail_count:],
        ]
        return "\n".join(candidate) + "\n"


def payload_processors() -> list:
    """Return fresh payload-aware processors."""
    return [
        BrowserPagePayloadProcessor(),
        JsonPayloadProcessor(),
        DiffPayloadProcessor(),
        LogPayloadProcessor(),
        TablePayloadProcessor(),
    ]

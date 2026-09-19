"""Pluggable, failure-aware command-output compression.

Processors own format-specific transformations. The registry owns routing,
failure policy, critical-line recovery, and the final ratio gate so a processor
cannot silently make output larger or discard an obvious diagnostic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

ERROR_HINTS = re.compile(
    r"(error|exception|fail|failed|fatal|panic|traceback|assert|expected|received)",
    re.I,
)
_STRONG_FAILURE = re.compile(
    r"(?im)(^\s*(?:FAILED|ERROR|FATAL|PANIC)\b|Traceback \(most recent call last\)|"
    r"\b(?:AssertionError|Exception|RuntimeError|TypeError|ValueError)\b)"
)
_CRITICAL = re.compile(
    r"(?i)(Traceback|AssertionError|\b(?:ERROR|FAILED|FATAL|PANIC)\b|Caused by:|"
    r"(?:^|\s)[\w./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|cs|rb|php):\d+)"
)
MAX_ERROR_LINES = 40
MAX_RECOVERED_LINES = 20

_PYTEST = re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b", re.I)
_JEST = re.compile(r"\b(jest|vitest|npm\s+test|pnpm\s+test|yarn\s+test)\b", re.I)
_GIT_LOG = re.compile(r"\bgit\s+log\b", re.I)
_NPM_INSTALL = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(i|install|ci)\b", re.I)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BLANK_RUN = re.compile(r"\n{3,}")
_HEX_BLOB = re.compile(r"\b[0-9a-fA-F]{96,}\b")

_FAIL_BLOCK = re.compile(
    r"^=+ FAILURES =+[\s\S]*?(?=^=+ (?:short test summary|warnings summary)|\Z)",
    re.M | re.I,
)
_SHORT_SUMMARY = re.compile(
    r"^=+ short test summary info =+[\s\S]*?(?=^=+ |\Z)",
    re.M | re.I,
)
_LAST_COUNTS = re.compile(r"=+ .*\d+ (passed|failed|error).* =+\s*$", re.I | re.M)


@dataclass(frozen=True)
class OutputResult:
    text: str
    processor: str
    compressed: bool
    failed: bool
    recovered_lines: tuple[str, ...] = ()

    @property
    def reduction(self) -> float:
        return 0.0


class OutputProcessor(Protocol):
    name: str
    priority: int
    handles_failure: bool

    def matches(self, command: str) -> bool: ...
    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str: ...


def _ensure_nl(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    return text + "\n"


def _collapse_repeated_lines(text: str, minimum: int = 3) -> str:
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
    if not text:
        return text
    out = _ANSI.sub("", text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _BLANK_RUN.sub("\n\n", out)
    out = _HEX_BLOB.sub(
        lambda match: match.group(0)[:12] + f"…({len(match.group(0))} hex)",
        out,
    )
    stripped = out.strip()
    if stripped[:1] in "{[" and stripped[-1:] in "}]":
        try:
            packed = json.dumps(
                json.loads(stripped), separators=(",", ":"), ensure_ascii=False
            )
            if len(packed) + 1 < len(out):
                out = packed + "\n"
                return out if len(out) <= len(text) else text
        except (ValueError, TypeError):
            pass
    out = _collapse_repeated_lines(out)
    return out if len(out) <= len(text) else text


def filter_text(
    text: str, max_lines: int = 80, keep_tail: int = 20, *,
    prepared: bool = False,
) -> str:
    if not prepared:
        text = preprocess(text)
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return _ensure_nl(text)

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
    return out if len(out) < len(text) else _ensure_nl(text)


def _pytest_slice(text: str) -> str | None:
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
    out = (
        f"[filtered pytest: {len(text.splitlines())} lines → failures/summary]\n"
        + body
        + "\n"
    )
    return out if len(out) < len(text) else None


def _keep_matching(
    text: str, pattern: re.Pattern[str], limit: int, label: str,
) -> str | None:
    lines = text.splitlines()
    kept = [line for line in lines if pattern.search(line)]
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


class PytestProcessor:
    name = "pytest"
    priority = 10
    handles_failure = True

    def matches(self, command: str) -> bool:
        return bool(_PYTEST.search(command))

    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str:
        return _pytest_slice(text) or (
            text if failed else filter_text(preprocess(text), max_lines, keep_tail, prepared=True)
        )


class JsTestProcessor:
    name = "js-test"
    priority = 20
    handles_failure = True

    def matches(self, command: str) -> bool:
        return bool(_JEST.search(command))

    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str:
        candidate = _keep_matching(
            text,
            re.compile(
                r"(FAIL|PASS|✕|×|Error|Expected|Received|Tests:|Test Suites:|Snapshots:)",
                re.I,
            ),
            limit=max(40, max_lines),
            label="test",
        )
        return candidate or (
            text if failed else filter_text(preprocess(text), max_lines, keep_tail, prepared=True)
        )


class GitLogProcessor:
    name = "git-log"
    priority = 30
    handles_failure = False

    def matches(self, command: str) -> bool:
        return bool(_GIT_LOG.search(command))

    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str:
        lines = preprocess(text).splitlines()
        if len(lines) <= 40:
            return _ensure_nl(text)
        clipped = (
            "\n".join(lines[:25])
            + f"\n[filtered git log: {len(lines) - 25} commits omitted]\n"
        )
        return clipped if len(clipped) < len(text) else text


class PackageInstallProcessor:
    name = "package-install"
    priority = 40
    handles_failure = False

    def matches(self, command: str) -> bool:
        return bool(_NPM_INSTALL.search(command))

    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str:
        candidate = _keep_matching(
            preprocess(text),
            re.compile(
                r"(ERR!|error|warn|added \d+|removed \d+|audited|packages? in)",
                re.I,
            ),
            limit=40,
            label="install",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, keep_tail, prepared=True
        )


class GenericProcessor:
    name = "generic"
    priority = 999
    handles_failure = True

    def matches(self, command: str) -> bool:
        return True

    def compress(
        self, command: str, text: str, *, failed: bool,
        max_lines: int, keep_tail: int,
    ) -> str:
        # Unknown failures are already information-dense. A format-specific
        # processor must explicitly opt into failure handling before we remove
        # anything from them.
        if failed:
            return text
        prepared = preprocess(text)
        return filter_text(prepared, max_lines, keep_tail, prepared=True)


class ProcessorRegistry:
    def __init__(self, processors: list[OutputProcessor] | None = None):
        selected = processors or [
            PytestProcessor(),
            JsTestProcessor(),
            GitLogProcessor(),
            PackageInstallProcessor(),
            GenericProcessor(),
        ]
        self.processors = sorted(selected, key=lambda item: (item.priority, item.name))
        if not any(item.name == "generic" for item in self.processors):
            raise ValueError("output processor registry requires a generic fallback")

    def select(self, command: str, *, failed: bool) -> OutputProcessor:
        for processor in self.processors:
            if failed and not processor.handles_failure:
                continue
            if processor.matches(command):
                return processor
        raise RuntimeError("no output processor matched")


DEFAULT_REGISTRY = ProcessorRegistry()


def detect_failure(text: str, exit_code: int | None = None) -> bool:
    if exit_code is not None:
        return exit_code != 0
    return bool(_STRONG_FAILURE.search(_ANSI.sub("", text)))


def _critical_lines(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in _ANSI.sub("", text).splitlines():
        key = line.strip()
        if not key or key in seen or not _CRITICAL.search(line):
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= MAX_RECOVERED_LINES:
            break
    return out


def recover_critical_lines(original: str, candidate: str) -> tuple[str, tuple[str, ...]]:
    present = {line.strip() for line in candidate.splitlines() if line.strip()}
    missing = tuple(
        line for line in _critical_lines(original) if line.strip() not in present
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


def process_output(
    text: str,
    command: str = "",
    *,
    exit_code: int | None = None,
    max_lines: int = 80,
    keep_tail: int = 20,
    min_reduction: float = 0.02,
    registry: ProcessorRegistry | None = None,
) -> OutputResult:
    if not text:
        return OutputResult(text, "none", False, False)
    failed = detect_failure(text, exit_code)
    active = registry or DEFAULT_REGISTRY
    processor = active.select(command, failed=failed)
    candidate = processor.compress(
        command, text, failed=failed, max_lines=max_lines, keep_tail=keep_tail
    )
    candidate, recovered = recover_critical_lines(text, candidate)

    original_bytes = len(text.encode())
    candidate_bytes = len(candidate.encode())
    reduction = (
        0.0 if original_bytes <= 0 else 1.0 - candidate_bytes / original_bytes
    )
    if candidate_bytes >= original_bytes or reduction < max(0.0, min_reduction):
        candidate = text
        recovered = ()
    return OutputResult(
        candidate,
        processor.name,
        candidate != text,
        failed,
        recovered,
    )


def explain_processor(
    command: str, *, exit_code: int | None = None, sample: str = "",
    registry: ProcessorRegistry | None = None,
) -> dict:
    failed = detect_failure(sample, exit_code)
    active = registry or DEFAULT_REGISTRY
    processor = active.select(command, failed=failed)
    skipped = [
        item.name
        for item in active.processors
        if item.matches(command) and failed and not item.handles_failure
    ]
    return {
        "command": command,
        "processor": processor.name,
        "failed": failed,
        "handles_failure": processor.handles_failure,
        "failure_skipped_processors": skipped,
    }

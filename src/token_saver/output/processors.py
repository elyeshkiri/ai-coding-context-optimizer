"""Built-in format-aware command-output processors."""

from __future__ import annotations

import re

from .text import ensure_newline, filter_text, preprocess

_PYTEST = re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b", re.I)
_JEST = re.compile(r"\b(jest|vitest|npm\s+test|pnpm\s+test|yarn\s+test)\b", re.I)
_GIT_LOG = re.compile(r"\bgit\s+log\b", re.I)
_NPM_INSTALL = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(i|install|ci)\b", re.I)
_FAIL_BLOCK = re.compile(
    r"^=+ FAILURES =+[\s\S]*?(?=^=+ (?:short test summary|warnings summary)|\Z)",
    re.M | re.I,
)
_SHORT_SUMMARY = re.compile(
    r"^=+ short test summary info =+[\s\S]*?(?=^=+ |\Z)",
    re.M | re.I,
)
_LAST_COUNTS = re.compile(r"=+ .*\d+ (passed|failed|error).* =+\s*$", re.I | re.M)


def pytest_slice(text: str) -> str | None:
    """Return a compact pytest failure/summary view when one is available."""
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


def keep_matching(
    text: str,
    pattern: re.Pattern[str],
    limit: int,
    label: str,
) -> str | None:
    """Keep bounded matching lines when that representation is smaller."""
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
    """Compress pytest output while retaining failure evidence."""

    name = "pytest"
    priority = 10
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether ``command`` invokes pytest."""
        return bool(_PYTEST.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Compress pytest output conservatively."""
        return pytest_slice(text) or (
            text
            if failed
            else filter_text(preprocess(text), max_lines, keep_tail, prepared=True)
        )


class JsTestProcessor:
    """Compress Jest/Vitest-style output while retaining complex failures."""

    name = "js-test"
    priority = 20
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether ``command`` invokes a supported JavaScript test runner."""
        return bool(_JEST.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Compress JavaScript test output conservatively."""
        complex_failure = failed and bool(
            re.search(r"(?m)^\s+at\s+|^\s*[+-]\s+.+$", text)
        )
        if complex_failure:
            return text
        candidate = keep_matching(
            text,
            re.compile(
                r"(FAIL|PASS|✕|×|Error|Expected|Received|Tests:|Test Suites:|Snapshots:)",
                re.I,
            ),
            limit=max(40, max_lines),
            label="test",
        )
        if candidate:
            return candidate
        prepared = preprocess(text)
        return filter_text(prepared, max_lines, keep_tail, prepared=True)


class GitLogProcessor:
    """Compress long ``git log`` output to the leading commit inventory."""

    name = "git-log"
    priority = 30
    handles_failure = False

    def matches(self, command: str) -> bool:
        """Return whether ``command`` is a git-log invocation."""
        return bool(_GIT_LOG.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Compress a long git log while preserving leading history."""
        lines = preprocess(text).splitlines()
        if len(lines) <= 40:
            return ensure_newline(text)
        clipped = (
            "\n".join(lines[:25])
            + f"\n[filtered git log: {len(lines) - 25} commits omitted]\n"
        )
        return clipped if len(clipped) < len(text) else text


class PackageInstallProcessor:
    """Compress successful package-manager installation chatter."""

    name = "package-install"
    priority = 40
    handles_failure = False

    def matches(self, command: str) -> bool:
        """Return whether ``command`` is a supported package installation."""
        return bool(_NPM_INSTALL.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Compress successful package installation output."""
        prepared = preprocess(text)
        candidate = keep_matching(
            prepared,
            re.compile(
                r"(ERR!|error|warn|added \d+|removed \d+|audited|packages? in)",
                re.I,
            ),
            limit=40,
            label="install",
        )
        return candidate or filter_text(
            prepared, max_lines, keep_tail, prepared=True
        )


class GenericProcessor:
    """Provide a conservative fallback for unknown command families."""

    name = "generic"
    priority = 999
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Match every command as the final fallback."""
        return True

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Compress only successful unknown output; failed output passes through."""
        if failed:
            return text
        prepared = preprocess(text)
        return filter_text(prepared, max_lines, keep_tail, prepared=True)


def default_processors() -> list:
    """Return fresh instances of the built-in processor set."""
    return [
        PytestProcessor(),
        JsTestProcessor(),
        GitLogProcessor(),
        PackageInstallProcessor(),
        GenericProcessor(),
    ]

"""Built-in format-aware command-output processors."""

from __future__ import annotations

import re

from .specialized_processors import extended_processors
from .text import ensure_newline, filter_text, preprocess

_PYTEST = re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b", re.I)
_JEST = re.compile(r"\b(jest|vitest|npm\s+test|pnpm\s+test|yarn\s+test)\b", re.I)
_GIT_LOG = re.compile(r"\bgit\s+log\b", re.I)
_NPM_INSTALL = re.compile(r"\b(npm|pnpm|yarn|bun|pip|pip3|uv)\s+(i|install|ci|sync)\b", re.I)
_GIT_STATUS = re.compile(r"\bgit\s+status\b", re.I)
_SEARCH = re.compile(r"(^|[;&|]\s*|\b)(rg|grep|find)\b", re.I)
_LINT = re.compile(r"\b(ruff|eslint|pylint|clippy)\b", re.I)
_TYPECHECK = re.compile(r"\b(tsc|mypy|pyright)\b", re.I)
_COMPILED_TEST = re.compile(r"\b(go\s+test|cargo\s+test|dotnet\s+test)\b", re.I)
_BUILD = re.compile(
    r"\b(cargo\s+build|go\s+build|gradle|gradlew|mvn|maven|"
    r"npm\s+run\s+build|pnpm\s+(?:run\s+)?build|yarn\s+build)\b",
    re.I,
)
_CONTAINER_LOG = re.compile(r"\b(docker\s+logs|kubectl\s+logs)\b", re.I)
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


class GitStatusProcessor:
    """Compress git status output while retaining changed-file inventory."""

    name = "git-status"
    priority = 31
    handles_failure = False

    def matches(self, command: str) -> bool:
        """Return whether the command invokes git status."""
        return bool(_GIT_STATUS.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep branch state plus bounded changed/untracked file lines."""
        del command, failed, keep_tail
        candidate = keep_matching(
            preprocess(text),
            re.compile(
                r"(^On branch|^Your branch|^Changes|^Untracked|^nothing to commit|"
                r"^\s*[MADRCU?!]{1,2}\s+|^\s*(modified|deleted|new file|renamed):|"
                r"^\s{2,}\S)",
                re.I,
            ),
            limit=max(40, max_lines),
            label="git status",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, 10, prepared=True
        )


class SearchProcessor:
    """Compress large grep/ripgrep/find result sets to bounded unique hits."""

    name = "search"
    priority = 35
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether the command is a supported search invocation."""
        return bool(_SEARCH.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep first unique result lines plus an omitted-result count."""
        del command, failed, keep_tail
        lines = preprocess(text).splitlines()
        unique: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            unique.append(line)
            if len(unique) >= max(25, max_lines):
                break
        omitted = len(lines) - len(unique)
        if omitted <= 0:
            return ensure_newline(text)
        result = (
            f"[filtered search: {len(lines)} lines → {len(unique)} unique hits, "
            f"{omitted} omitted]\n"
            + "\n".join(unique)
            + "\n"
        )
        return result if len(result) < len(text) else text


class LintProcessor:
    """Compress common linter output while preserving file diagnostics."""

    name = "lint"
    priority = 36
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether the command invokes a supported linter."""
        return bool(_LINT.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep location-bearing diagnostics and summary lines."""
        del command, failed, keep_tail
        candidate = keep_matching(
            preprocess(text),
            re.compile(
                r"(:\d+(?::\d+)?\b|\berror\b|\bwarning\b|"
                r"\bproblems?\b|\bfound\s+\d+\b|\bE\d{3,4}\b|\bW\d{3,4}\b)",
                re.I,
            ),
            limit=max(60, max_lines),
            label="lint",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, 12, prepared=True
        )


class TypecheckProcessor:
    """Compress compiler/typechecker diagnostics without hiding locations."""

    name = "typecheck"
    priority = 37
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether the command invokes a supported typechecker."""
        return bool(_TYPECHECK.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep typed diagnostics, source locations, and summaries."""
        del command, failed, keep_tail
        candidate = keep_matching(
            preprocess(text),
            re.compile(
                r"(error\s+TS\d+|:\d+(?::\d+)?\b|\berror:|"
                r"\bnote:|Found \d+ error|Success: no issues)",
                re.I,
            ),
            limit=max(60, max_lines),
            label="typecheck",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, 12, prepared=True
        )


class CompiledTestProcessor:
    """Compress Go/Cargo test output to failures and final package summaries."""

    name = "compiled-test"
    priority = 38
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether the command invokes Go or Cargo tests."""
        return bool(_COMPILED_TEST.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep test failures, panic/error lines, and package/result summaries."""
        del command, failed, keep_tail
        candidate = keep_matching(
            preprocess(text),
            re.compile(
                r"(--- FAIL:|\bFAIL\b|\bPASS\b|panicked at|\berror\b|"
                r"test result:|^ok\s|^\?\s|^FAIL\s|Failed!|Passed!|Total tests:|Failed:|Passed:)",
                re.I,
            ),
            limit=max(60, max_lines),
            label="compiled tests",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, 12, prepared=True
        )


class BuildProcessor:
    """Compress common build output while retaining diagnostic evidence."""

    name = "build"
    priority = 39
    handles_failure = True

    def matches(self, command: str) -> bool:
        """Return whether the command invokes a supported build system."""
        return bool(_BUILD.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep build errors/warnings and terminal status lines."""
        del command, failed
        candidate = keep_matching(
            preprocess(text),
            re.compile(
                r"(\berror\b|\bwarning\b|FAILED|BUILD (?:SUCCESS|FAIL)|"
                r"Finished|:\d+(?::\d+)?\b)",
                re.I,
            ),
            limit=max(70, max_lines),
            label="build",
        )
        return candidate or filter_text(
            preprocess(text), max_lines, max(keep_tail, 15), prepared=True
        )


class ContainerLogProcessor:
    """Bound successful Docker/Kubernetes log dumps while preserving their tail."""

    name = "container-log"
    priority = 41
    handles_failure = False

    def matches(self, command: str) -> bool:
        """Return whether the command requests Docker or Kubernetes logs."""
        return bool(_CONTAINER_LOG.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Retain a bounded head/tail view for successful log commands."""
        del command, failed
        return filter_text(
            preprocess(text),
            max_lines,
            max(keep_tail, 20),
            prepared=True,
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
    """Return fresh instances of the complete built-in processor set."""
    return [
        PytestProcessor(),
        JsTestProcessor(),
        GitLogProcessor(),
        GitStatusProcessor(),
        SearchProcessor(),
        LintProcessor(),
        TypecheckProcessor(),
        CompiledTestProcessor(),
        BuildProcessor(),
        PackageInstallProcessor(),
        ContainerLogProcessor(),
        GenericProcessor(),
        *extended_processors(),
    ]

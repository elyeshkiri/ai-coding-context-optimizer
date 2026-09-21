"""Specialized command-output processors for common developer CLIs."""

from __future__ import annotations

import re

from .text import filter_text, preprocess


class SpecializedLineProcessor:
    """Retain bounded command-specific evidence from one CLI family."""

    def __init__(
        self,
        name: str,
        priority: int,
        command_pattern: str,
        line_pattern: str,
        label: str,
        handles_failure: bool,
        limit_floor: int = 80,
        preserve_all_matches: bool = False,
    ) -> None:
        """Create a processor from declarative routing and preservation rules."""
        self.name = name
        self.priority = priority
        self.handles_failure = handles_failure
        self.label = label
        self.limit_floor = limit_floor
        self.preserve_all_matches = preserve_all_matches
        self._command = re.compile(command_pattern, re.I)
        self._line = re.compile(line_pattern, re.I)

    def matches(self, command: str) -> bool:
        """Return whether the command belongs to this processor."""
        return bool(self._command.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Return command-specific evidence or the conservative text fallback."""
        del command, failed
        prepared = preprocess(text)
        lines = prepared.splitlines()
        matched = [line for line in lines if self._line.search(line)]
        if matched:
            limit = len(matched) if self.preserve_all_matches else max(
                self.limit_floor, max_lines
            )
            kept = matched[:limit]
            omitted = len(lines) - len(kept)
            if omitted > 0:
                candidate = (
                    f"[filtered {self.label}: {len(lines)} lines → "
                    f"{len(kept)} kept, {omitted} omitted]\n"
                    + "\n".join(kept)
                    + "\n"
                )
                if len(candidate.encode()) < len(text.encode()):
                    return candidate
        return filter_text(
            prepared,
            max_lines,
            max(keep_tail, 12),
            prepared=True,
        )


class GitDiffProcessor:
    """Compact patches to file/hunk identity plus exact changed lines."""

    name = "git-diff"
    priority = 24
    handles_failure = False
    _command = re.compile(r"^\s*git\b.*\bdiff\b", re.I)

    def matches(self, command: str) -> bool:
        """Return whether the command is a git diff invocation."""
        return bool(self._command.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Remove index/context boilerplate while preserving patch semantics."""
        del command, failed, max_lines, keep_tail
        prepared = preprocess(text)
        lines = prepared.splitlines()
        if not any(line.startswith("diff --git ") for line in lines):
            return prepared

        kept = [
            line
            for line in lines
            if (
                line.startswith(("diff --git ", "@@ ", "@@@ "))
                or (line.startswith("+") and not line.startswith("+++"))
                or (line.startswith("-") and not line.startswith("---"))
                or line.startswith(
                    (
                        "new file mode ",
                        "deleted file mode ",
                        "old mode ",
                        "new mode ",
                        "similarity index ",
                        "rename from ",
                        "rename to ",
                        "copy from ",
                        "copy to ",
                        "Binary files ",
                        "GIT binary patch",
                        "\\ No newline at end of file",
                    )
                )
            )
        ]
        if not kept:
            return prepared
        candidate = "\n".join(kept) + "\n"
        return candidate if len(candidate.encode()) < len(text.encode()) else text


class GoBuildProcessor:
    """Compact Go compiler failures to exact actionable diagnostics."""

    name = "go-build"
    priority = 34
    handles_failure = True
    _command = re.compile(r"^\s*go\s+build\b", re.I)
    _diagnostic = re.compile(
        r"(?:\.go:\d+(?::\d+)?:|undefined:|cannot use|syntax error|"
        r"too many arguments|not enough arguments|invalid operation|link:)"
    )

    def matches(self, command: str) -> bool:
        """Return whether the command is a Go build invocation."""
        return bool(self._command.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep exact compiler diagnostics and only needed package context."""
        del command, failed, max_lines, keep_tail
        prepared = preprocess(text)
        lines = prepared.splitlines()
        packages = [line for line in lines if line.startswith("# ")]
        diagnostics = [line for line in lines if self._diagnostic.search(line)]
        if not diagnostics:
            return prepared

        kept = [*packages, *diagnostics] if len(packages) > 1 else diagnostics
        candidate = "\n".join(dict.fromkeys(kept)) + "\n"
        return candidate if len(candidate.encode()) < len(text.encode()) else text


class GoTestProcessor:
    """Compact Go test output to failures, locations, and package summaries."""

    name = "go-test"
    priority = 34
    handles_failure = True
    _command = re.compile(r"^\s*go\s+test\b", re.I)
    _diagnostic = re.compile(
        r"(?:\.go:\d+(?::\d+)?:|^--- FAIL:|^panic:|^FAIL\s+\S+|"
        r"undefined:|cannot use|syntax error)"
    )

    def matches(self, command: str) -> bool:
        """Return whether the command is a Go test invocation."""
        return bool(self._command.search(command))

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Keep exact failing-test evidence while dropping pass/build chatter."""
        del command, failed, max_lines, keep_tail
        prepared = preprocess(text)
        lines = prepared.splitlines()
        packages = [line for line in lines if line.startswith("# ")]
        kept = [line for line in lines if self._diagnostic.search(line)]
        if len(packages) > 1:
            kept = [*packages, *kept]
        if not kept:
            return prepared
        candidate = "\n".join(dict.fromkeys(kept)) + "\n"
        return candidate if len(candidate.encode()) < len(text.encode()) else text


# name, priority, command regex, evidence regex, label, handles_failure,
# minimum kept-line budget, preserve every matching line
_SPECS = [
    ("git-show", 25, r"^\s*git\b.*\bshow\b", r"^(?:commit |Author:|Date:|diff --git |index |--- |\+\+\+ |@@|[+-](?![+-]))", "git show", False, 120, True),
    ("git-branch", 26, r"^\s*git\s+branch\b", r".+", "git branch", False, 80, False),
    ("git-remote", 27, r"^\s*git\b.*\b(?:push|pull|fetch|remote)\b", r"(?:^From |^To |->|\[new |\[rejected\]|up.to.date|fast-forward|error:|fatal:|warning:)", "git remote", True, 80, False),
    ("docker-build", 32, r"^\s*docker\s+(?:build|buildx\s+build)\b", r"(?:^#\d+\s+\[|\b(?:ERROR|FAILED|CACHED|DONE)\b|error:|warning:|Successfully|exporting)", "docker build", True, 90, False),
    ("docker-ps", 32, r"^\s*docker\s+(?:container\s+)?(?:ps|ls)\b", r".+", "docker ps", False, 70, False),
    ("docker-compose", 32, r"^\s*(?:docker\s+compose|docker-compose)\b", r"(?:\b(?:Created|Started|Running|Healthy|Exited|Stopped|ERROR|Error|failed)\b|^\S+\s+\|)", "docker compose", True, 90, False),
    ("docker-inspect", 32, r"^\s*docker\s+(?:container\s+)?inspect\b", r".+", "docker inspect", False, 90, False),
    ("kubectl-get", 33, r"^\s*kubectl\s+get\b", r".+", "kubectl get", False, 80, False),
    ("kubectl-describe", 33, r"^\s*kubectl\s+describe\b", r"(?:^Name:|^Namespace:|^Status:|^Conditions:|^Events:|\b(?:Warning|Failed|Error|Unhealthy|BackOff|Reason|Message):?\b)", "kubectl describe", True, 100, False),
    ("kubectl-events", 33, r"^\s*kubectl\s+(?:get\s+events|events)\b", r".+", "kubectl events", True, 100, False),
    ("terraform-plan", 33, r"^\s*terraform\s+plan\b", r"(?:^Plan:|^No changes\.|^\s*# |^\s*[+~!-]\s|Error:|Warning:|Changes to Outputs:)", "terraform plan", True, 100, False),
    ("terraform-apply", 33, r"^\s*terraform\s+(?:apply|destroy)\b", r"(?:Apply complete!|Destroy complete!|^\s*# |^\s*[+~!-]\s|Error:|Warning:|: Creating|: Modifying|: Destroying|: Creation complete|: Destruction complete)", "terraform apply", True, 100, False),
    ("helm", 33, r"^\s*helm\b", r"(?:^NAME:|^STATUS:|^REVISION:|^NAMESPACE:|deployed|upgraded|uninstalled|Error:|WARNING:|FAILED)", "helm", True, 90, False),
    ("pulumi", 33, r"^\s*pulumi\b", r"(?:Resources:|Outputs:|Diagnostics:|error:|warning:|\b(?:create|update|delete|replace|same)\b|failed)", "pulumi", True, 100, False),
    ("cargo-build", 34, r"^\s*cargo\s+(?:build|check)\b", r"(?:^error(?:\[E\d+\])?:|^warning:|^\s*-->\s|^\s*= (?:help|note):|Finished|could not compile)", "cargo build", True, 100, False),
    ("cargo-clippy", 34, r"^\s*cargo\s+clippy\b", r"(?:^error(?:\[E\d+\])?:|^warning:|^\s*-->\s|^\s*= (?:help|note):|Finished|could not compile)", "cargo clippy", True, 100, False),
    ("cargo-test", 34, r"^\s*cargo\s+test\b", r"(?:test result:|^test .+ \.\.\. (?:FAILED|ignored)|panicked at|^failures:|^error:|FAILED)", "cargo test", True, 100, False),
    ("maven", 34, r"^\s*(?:\./)?mvnw?\b", r"(?:\[ERROR\]|\[WARNING\]|BUILD (?:SUCCESS|FAILURE)|Tests run:|Failures:|Errors:|Failed to execute goal)", "maven", True, 100, False),
    ("gradle", 34, r"^\s*(?:\./)?gradlew?\b", r"(?:^> Task .+ (?:FAILED|UP-TO-DATE)|BUILD (?:SUCCESSFUL|FAILED)|FAILURE:|\* What went wrong:|error:|warning:)", "gradle", True, 100, False),
    ("ruff", 34, r"^\s*(?:python\s+-m\s+)?ruff\b", r"(?:^.+:\d+:\d+:\s+[A-Z]+\d+\s|^Found \d+ error|^All checks passed)", "ruff", True, 120, False),
    ("eslint", 34, r"^\s*(?:npx\s+|pnpm\s+exec\s+|yarn\s+)?eslint\b", r"(?:^.+\.(?:js|jsx|ts|tsx|vue)$|^\s*\d+:\d+\s+(?:error|warning)\s|✖|problems? \()", "eslint", True, 120, False),
    ("pylint", 34, r"^\s*(?:python\s+-m\s+)?pylint\b", r"(?:^.+:\d+:\d+:\s+[A-Z]\d{4}:|Your code has been rated|rated at)", "pylint", True, 120, False),
    ("tsc", 34, r"^\s*(?:npx\s+|pnpm\s+exec\s+|yarn\s+)?tsc\b", r"(?:^.+\(\d+,\d+\):\s+error\s+TS\d+:|Found \d+ errors?)", "tsc", True, 120, False),
    ("mypy", 34, r"^\s*(?:python\s+-m\s+)?mypy\b", r"(?:^.+:\d+(?::\d+)?:\s+(?:error|note):|Found \d+ errors?|Success: no issues found)", "mypy", True, 120, False),
    ("jq-yq", 34, r"^\s*(?:jq|yq)\b", r".+", "structured query", True, 100, False),
]


def extended_processors() -> list:
    """Return the 28 specialized processors added to the core inventory."""
    return [
        GitDiffProcessor(),
        GoBuildProcessor(),
        GoTestProcessor(),
        *[SpecializedLineProcessor(*spec) for spec in _SPECS],
    ]

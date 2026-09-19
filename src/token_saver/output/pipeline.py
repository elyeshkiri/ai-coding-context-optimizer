"""Host-independent orchestration for command-output optimization."""

from __future__ import annotations

import re

from .contracts import OutputPolicy, OutputResult
from .registry import DEFAULT_REGISTRY, ProcessorRegistry
from .text import recover_critical_lines, strip_ansi

_STRONG_FAILURE = re.compile(
    r"(?im)(^\s*(?:FAIL|FAILED|ERROR|FATAL|PANIC)\b|Traceback \(most recent call last\)|"
    r"\b(?:AssertionError|Exception|RuntimeError|TypeError|ValueError)\b)"
)


def detect_failure(text: str, exit_code: int | None = None) -> bool:
    """Classify command failure from an exit code or strong output evidence."""
    if exit_code is not None:
        return exit_code != 0
    return bool(_STRONG_FAILURE.search(strip_ansi(text)))


class OutputPipeline:
    """Coordinate failure detection, routing, recovery, and size acceptance."""

    def __init__(self, registry: ProcessorRegistry | None = None):
        """Create a pipeline using an explicit or default processor registry."""
        self.registry = registry or DEFAULT_REGISTRY

    def process(
        self,
        text: str,
        command: str = "",
        *,
        exit_code: int | None = None,
        policy: OutputPolicy | None = None,
    ) -> OutputResult:
        """Optimize one captured stdout payload under ``policy``."""
        active_policy = policy or OutputPolicy()
        if not text:
            return OutputResult(text, "none", False, False)
        failed = detect_failure(text, exit_code)
        processor = self.registry.select(command, failed=failed)
        candidate = processor.compress(
            command,
            text,
            failed=failed,
            max_lines=active_policy.max_lines,
            keep_tail=active_policy.keep_tail,
        )
        candidate, recovered = recover_critical_lines(text, candidate)

        original_bytes = len(text.encode())
        candidate_bytes = len(candidate.encode())
        reduction = (
            0.0
            if original_bytes <= 0
            else 1.0 - candidate_bytes / original_bytes
        )
        if (
            candidate_bytes >= original_bytes
            or reduction < max(0.0, active_policy.min_reduction)
        ):
            candidate = text
            recovered = ()
        return OutputResult(
            candidate,
            processor.name,
            candidate != text,
            failed,
            recovered,
        )

    def explain(
        self,
        command: str,
        *,
        exit_code: int | None = None,
        sample: str = "",
    ) -> dict:
        """Explain which processor would handle a command and why."""
        failed = detect_failure(sample, exit_code)
        processor = self.registry.select(command, failed=failed)
        skipped = [
            item.name
            for item in self.registry.processors
            if item.matches(command) and failed and not item.handles_failure
        ]
        return {
            "command": command,
            "processor": processor.name,
            "failed": failed,
            "handles_failure": processor.handles_failure,
            "failure_skipped_processors": skipped,
        }


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
    """Compatibility function for one-shot output processing."""
    return OutputPipeline(registry).process(
        text,
        command,
        exit_code=exit_code,
        policy=OutputPolicy(
            max_lines=max_lines,
            keep_tail=keep_tail,
            min_reduction=min_reduction,
        ),
    )


def explain_processor(
    command: str,
    *,
    exit_code: int | None = None,
    sample: str = "",
    registry: ProcessorRegistry | None = None,
) -> dict:
    """Compatibility function for explaining processor selection."""
    return OutputPipeline(registry).explain(
        command,
        exit_code=exit_code,
        sample=sample,
    )

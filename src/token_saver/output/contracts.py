"""Stable contracts for command-output optimization.

The output package keeps transformation implementations behind small protocols so
routing and orchestration can be tested or extended without importing concrete
processors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OutputResult:
    """Describe the result of one output-optimization pass."""

    text: str
    processor: str
    compressed: bool
    failed: bool
    recovered_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputPolicy:
    """Configure size and preservation thresholds for one pipeline run."""

    max_lines: int = 80
    keep_tail: int = 20
    min_reduction: float = 0.02


class OutputProcessor(Protocol):
    """Transform output for one recognized command family."""

    name: str
    priority: int
    handles_failure: bool

    def matches(self, command: str) -> bool:
        """Return whether this processor recognizes ``command``."""
        ...

    def compress(
        self,
        command: str,
        text: str,
        *,
        failed: bool,
        max_lines: int,
        keep_tail: int,
    ) -> str:
        """Return a conservative transformed representation of ``text``."""
        ...

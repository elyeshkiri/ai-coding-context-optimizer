"""Processor registration and routing for command-output optimization."""

from __future__ import annotations

from .contracts import OutputProcessor
from .processors import default_processors


class ProcessorRegistry:
    """Own processor ordering and failure-aware command routing."""

    def __init__(self, processors: list[OutputProcessor] | None = None):
        """Create a registry from explicit processors or the built-in set."""
        selected = processors or default_processors()
        self.processors = sorted(
            selected, key=lambda item: (item.priority, item.name)
        )
        if not any(item.name == "generic" for item in self.processors):
            raise ValueError("output processor registry requires a generic fallback")

    def select(self, command: str, *, failed: bool) -> OutputProcessor:
        """Return the first eligible processor for ``command``."""
        for processor in self.processors:
            if failed and not processor.handles_failure:
                continue
            if processor.matches(command):
                return processor
        raise RuntimeError("no output processor matched")


DEFAULT_REGISTRY = ProcessorRegistry()

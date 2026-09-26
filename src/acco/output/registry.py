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

    def select(
        self,
        command: str,
        *,
        failed: bool,
        text: str = "",
    ) -> OutputProcessor:
        """Return the best command- or payload-aware processor."""
        generic: OutputProcessor | None = None
        for processor in self.processors:
            if processor.name == "generic":
                generic = processor
                continue
            if failed and not processor.handles_failure:
                continue
            if processor.matches(command):
                return processor

        if text:
            for processor in self.processors:
                if processor.name == "generic":
                    continue
                if failed and not processor.handles_failure:
                    continue
                matcher = getattr(processor, "matches_payload", None)
                if callable(matcher) and matcher(text):
                    return processor

        if generic is not None:
            return generic
        raise RuntimeError("no output processor matched")


DEFAULT_REGISTRY = ProcessorRegistry()

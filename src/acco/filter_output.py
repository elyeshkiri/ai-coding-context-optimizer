"""Compatibility facade for pluggable command-output compression."""

from __future__ import annotations

from .output_processors import (
    ERROR_HINTS,
    ProcessorRegistry,
    explain_processor,
    filter_text,
    preprocess,
    process_output,
)


def filter_command_output(
    text: str,
    command: str = "",
    max_lines: int = 80,
    keep_tail: int = 20,
    *,
    exit_code: int | None = None,
    registry: ProcessorRegistry | None = None,
) -> str:
    """Compress command output through the failure-aware processor registry."""
    return process_output(
        text,
        command,
        exit_code=exit_code,
        max_lines=max_lines,
        keep_tail=keep_tail,
        registry=registry,
    ).text


__all__ = [
    "ERROR_HINTS",
    "ProcessorRegistry",
    "explain_processor",
    "filter_command_output",
    "filter_text",
    "preprocess",
    "process_output",
]

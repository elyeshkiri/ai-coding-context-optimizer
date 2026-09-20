"""Session-efficiency services: continuity, deduplication, waste signals, and reports."""

from .report import dashboard_report
from .service import (
    continuity_context,
    deduplicate_output,
    observe_prompt,
    observe_tool,
    start_session,
)

__all__ = [
    "continuity_context",
    "dashboard_report",
    "deduplicate_output",
    "observe_prompt",
    "observe_tool",
    "start_session",
]

"""Session-efficiency services: continuity, deduplication, waste signals, and reports."""

from .report import continuity_report, dashboard_report
from .service import (
    continuity_context,
    deduplicate_output,
    observe_prompt,
    observe_tool,
    start_session,
)

__all__ = [
    "continuity_context",
    "continuity_report",
    "dashboard_report",
    "deduplicate_output",
    "observe_prompt",
    "observe_tool",
    "start_session",
]

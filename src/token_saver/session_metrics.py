"""Independent session-efficiency metrics derived from transcripts and local events."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .output.pipeline import detect_failure
from .sessions import analyze

_SPACE = re.compile(r"\s+")


def _normalized_command(value: object) -> str | None:
    """Return a stable normalized Bash command without persisting it."""
    if not isinstance(value, str) or not value.strip():
        return None
    return _SPACE.sub(" ", value.strip())


def _digest(value: str) -> str:
    """Return a short stable digest for one observed result."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def _result_text(value: object) -> str:
    """Render a tool result deterministically for failure/digest analysis."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return str(value)


def _exit_code(value: object) -> int | None:
    """Extract common Bash exit-code fields from a tool-result object."""
    if not isinstance(value, dict):
        return None
    for key in ("exitCode", "exit_code", "code"):
        found = value.get(key)
        if isinstance(found, int) and not isinstance(found, bool):
            return found
    return None


def _tool_result_id(record: dict) -> str | None:
    """Resolve the tool-use id associated with one transcript result record."""
    for key in ("toolUseID", "toolUseId", "tool_use_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        for key in ("tool_use_id", "toolUseId"):
            value = block.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def transcript_session_metrics(path: Path) -> dict:
    """Measure tool/retry/read behavior independently from Token Saver events."""
    report = analyze([path], keep_content=False)
    duplicate_reads = sum(max(0, count - 1) for _path, count, _tokens in report.duplicate_reads())

    uses: dict[str, tuple[str, dict]] = {}
    command_counts: Counter[str] = Counter()
    failed_result_counts: Counter[tuple[str, str]] = Counter()
    repeat_command_calls = 0
    retry_attempts = 0
    bash_calls = 0

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []

    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message")
        if isinstance(message, dict) and record.get("type") == "assistant":
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_id = block.get("id")
                name = block.get("name")
                tool_input = block.get("input")
                if (
                    isinstance(tool_id, str)
                    and tool_id
                    and isinstance(name, str)
                    and isinstance(tool_input, dict)
                ):
                    uses[tool_id] = (name, tool_input)

        if "toolUseResult" not in record:
            continue
        tool_id = _tool_result_id(record)
        if not tool_id or tool_id not in uses:
            continue
        name, tool_input = uses[tool_id]
        if name != "Bash":
            continue
        command = _normalized_command(tool_input.get("command"))
        if command is None:
            continue
        bash_calls += 1
        command_id = _digest(command)
        if command_counts[command_id] >= 1:
            repeat_command_calls += 1
        command_counts[command_id] += 1

        result = record.get("toolUseResult")
        text = _result_text(result)
        if detect_failure(text, _exit_code(result)):
            failure_key = (command_id, _digest(text))
            if failed_result_counts[failure_key] >= 1:
                retry_attempts += 1
            failed_result_counts[failure_key] += 1

    return {
        "tool_calls": len(report.calls),
        "bash_calls": bash_calls,
        "unique_bash_commands": len(command_counts),
        "repeat_command_calls": repeat_command_calls,
        "retry_attempts": retry_attempts,
        "duplicate_read_calls": duplicate_reads,
    }


def load_efficiency_events_from_state(state_root: Path) -> list[dict]:
    """Load all valid session-efficiency events from one isolated run state."""
    base = state_root / "efficiency"
    if not base.is_dir():
        return []
    events: list[dict] = []
    for path in sorted(base.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("schema") == 1:
                events.append(item)
    return events


def efficiency_event_metrics(state_root: Path) -> dict:
    """Summarize treatment-side interventions without using them as outcome truth."""
    events = load_efficiency_events_from_state(state_root)
    savings = Counter()
    waste = Counter()
    continuity = 0
    estimated_saved = 0
    for event in events:
        kind = event.get("kind")
        feature = str(event.get("feature") or "unknown")
        if kind == "saving":
            savings[feature] += 1
            value = event.get("estimated_tokens_saved")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                estimated_saved += value
        elif kind == "waste":
            waste[feature] += 1
        elif kind == "continuity":
            continuity += 1
    return {
        "events": len(events),
        "continuity_restores": continuity,
        "dedup_interventions": (
            savings["cross_turn_dedup"] + savings["unchanged_read_block"]
        ),
        "cross_turn_output_dedups": savings["cross_turn_dedup"],
        "unchanged_read_blocks": savings["unchanged_read_block"],
        "knowledge_read_avoidance": savings["knowledge_read_avoidance"],
        "cache_economic_read_avoidance": sum(
            1
            for event in events
            if event.get("kind") == "saving"
            and event.get("feature") == "knowledge_read_avoidance"
            and isinstance(event.get("cache_economics"), dict)
        ),
        "waste_signals": sum(waste.values()),
        "retry_loop_signals": waste["retry_loop"],
        "repeated_command_signals": waste["repeated_command"],
        "tool_cascade_signals": waste["tool_cascade"],
        "estimated_tool_context_tokens_saved": estimated_saved,
    }

"""Local, content-free telemetry for generation-budget effectiveness.

The hook records only policy metadata and transcript usage counters. Prompt text,
assistant text, tool payloads, and transcript contents are never persisted here.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .state import load as load_state
from .state import state_dir
from .state import update as update_state

USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
TELEMETRY_SCHEMA = 1
MAX_TELEMETRY_BYTES = 4 * 1024 * 1024
KEEP_RECORDS_AFTER_COMPACTION = 2000


def _project_id(root: Path) -> str:
    """Return a stable opaque project identifier for local telemetry storage."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()


def telemetry_path(root: Path) -> Path:
    """Return the project-scoped local JSONL telemetry path."""
    return state_dir() / "telemetry" / f"{_project_id(root)}.jsonl"


def _session_fingerprint(session_id: str | None) -> str | None:
    """Return a short opaque session fingerprint without storing the raw id."""
    if not session_id:
        return None
    return hashlib.sha256(session_id.encode()).hexdigest()[:16]


def _transcript_offset(raw_path: object) -> int | None:
    """Return the current transcript byte length, or None when it is unreadable."""
    if not raw_path:
        return None
    path = Path(str(raw_path)).expanduser()
    try:
        if not path.exists():
            return 0
        return path.stat().st_size
    except OSError:
        return None


def start_output_turn(
    root: Path,
    *,
    transcript_path: object,
    session_id: str | None = None,
    prompt_id: object = None,
) -> None:
    """Checkpoint one turn without persisting prompt or response content."""
    policy = load_state(root, session_id).get("output_policy")
    policy = policy if isinstance(policy, dict) else {}
    route = load_state(root, session_id).get("model_route")
    route = route if isinstance(route, dict) else {}
    pending = {
        "schema": TELEMETRY_SCHEMA,
        "offset": _transcript_offset(transcript_path),
        "started_at": int(time.time()),
        "prompt_id": str(prompt_id) if prompt_id else None,
        "experiment": {
            "task": os.environ.get("TOKEN_SAVER_BENCHMARK_TASK"),
            "trial": os.environ.get("TOKEN_SAVER_BENCHMARK_TRIAL"),
            "condition": os.environ.get("TOKEN_SAVER_BENCHMARK_CONDITION"),
        },
        "policy": {
            key: policy.get(key)
            for key in (
                "task",
                "mode",
                "max_tokens",
                "adaptive",
                "complexity_score",
                "complexity_tier",
                "calibrated",
                "calibration_samples",
            )
            if key in policy
        },
        "model_route": {
            key: route.get(key)
            for key in (
                "task",
                "complexity_tier",
                "risk_level",
                "minimum_capability",
                "selected_model",
                "action",
                "pricing_basis",
                "projected_savings_fraction",
                "projected_selected_cost_usd",
                "calibration_applied",
                "calibration_source",
            )
            if key in route
        },
    }

    def mutate(data: dict) -> None:
        data["output_telemetry_pending"] = pending

    update_state(root, mutate, session_id)


def _usage_since(path: Path, offset: int | None) -> dict:
    """Read only transcript bytes appended after a prompt checkpoint."""
    empty = {
        "usage_available": False,
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_5m_input_tokens": 0,
        "cache_creation_1h_input_tokens": 0,
        "output_tokens": 0,
        "model_calls": 0,
        "models": [],
    }
    if offset is None:
        return empty
    try:
        size = path.stat().st_size
        if size < offset:
            return empty
        with path.open("rb") as handle:
            handle.seek(offset)
            raw_lines = handle.readlines()
    except OSError:
        return empty

    messages: dict[str, dict[str, Any]] = {}
    anonymous = 0
    for raw in raw_lines:
        try:
            record = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict) or not usage:
            continue
        message_id = message.get("id")
        if message_id:
            key = str(message_id)
        else:
            anonymous += 1
            key = f"anonymous-{anonymous}"
        item = messages.setdefault(
            key,
            {
                "model": str(message.get("model") or "unknown"),
                **dict.fromkeys(USAGE_FIELDS, 0),
                "cache_creation_5m_input_tokens": 0,
                "cache_creation_1h_input_tokens": 0,
            },
        )
        if item["model"] == "unknown" and message.get("model"):
            item["model"] = str(message["model"])
        for field in USAGE_FIELDS:
            value = usage.get(field, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                item[field] = max(int(item[field]), value)
        breakdown = usage.get("cache_creation")
        if isinstance(breakdown, dict):
            for source, target in (
                ("ephemeral_5m_input_tokens", "cache_creation_5m_input_tokens"),
                ("ephemeral_1h_input_tokens", "cache_creation_1h_input_tokens"),
            ):
                value = breakdown.get(source, 0)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    item[target] = max(int(item[target]), value)

    if not messages:
        return empty

    return {
        "usage_available": True,
        **{
            field: sum(int(item[field]) for item in messages.values())
            for field in USAGE_FIELDS
        },
        "cache_creation_5m_input_tokens": sum(
            int(item["cache_creation_5m_input_tokens"]) for item in messages.values()
        ),
        "cache_creation_1h_input_tokens": sum(
            int(item["cache_creation_1h_input_tokens"]) for item in messages.values()
        ),
        "model_calls": len(messages),
        "models": sorted({str(item["model"]) for item in messages.values()}),
    }


def _locked_append(path: Path, record: dict) -> None:
    """Append one JSON record under a cross-platform file lock."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            existed = path.exists()
            with path.open("a", encoding="utf-8") as handle:
                json.dump(record, handle, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if not existed:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            _compact_if_needed(path)
        finally:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _compact_if_needed(path: Path) -> None:
    """Bound telemetry storage while preserving the newest complete records."""
    try:
        if path.stat().st_size <= MAX_TELEMETRY_BYTES:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    kept = lines[-KEEP_RECORDS_AFTER_COMPACTION:]
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if kept:
                handle.write("\n".join(kept) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def finish_output_turn(
    root: Path,
    *,
    transcript_path: object,
    session_id: str | None = None,
    status: str = "completed",
    error: object = None,
) -> dict | None:
    """Persist usage for the pending turn and consume its checkpoint."""
    state = load_state(root, session_id)
    pending = state.get("output_telemetry_pending")
    if not isinstance(pending, dict):
        return None

    offset = pending.get("offset")
    if isinstance(offset, bool) or (offset is not None and not isinstance(offset, int)):
        offset = None
    path = Path(str(transcript_path)).expanduser() if transcript_path else None
    usage = _usage_since(path, offset) if path is not None else _usage_since(Path("."), None)
    policy = pending.get("policy")
    policy = policy if isinstance(policy, dict) else {}

    model_route = pending.get("model_route")
    model_route = model_route if isinstance(model_route, dict) else {}
    route_target = model_route.get("selected_model")
    if not isinstance(route_target, str) or not route_target:
        route_target = None

    budget = policy.get("max_tokens")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        budget = None
    output_tokens = int(usage["output_tokens"])
    utilization = (
        output_tokens / budget
        if usage["usage_available"] and budget is not None
        else None
    )
    record = {
        "schema": TELEMETRY_SCHEMA,
        "recorded_at": int(time.time()),
        "session": _session_fingerprint(session_id),
        "prompt_id": pending.get("prompt_id"),
        "experiment": pending.get("experiment"),
        "turn_status": status,
        "error": str(error) if error else None,
        "task": policy.get("task"),
        "mode": policy.get("mode"),
        "selected_budget": budget,
        "adaptive": policy.get("adaptive"),
        "complexity_score": policy.get("complexity_score"),
        "complexity_tier": policy.get("complexity_tier"),
        "calibrated": policy.get("calibrated"),
        "calibration_samples": policy.get("calibration_samples"),
        "route_task": model_route.get("task"),
        "route_complexity_tier": model_route.get("complexity_tier"),
        "route_risk_level": model_route.get("risk_level"),
        "route_minimum_capability": model_route.get("minimum_capability"),
        "route_target_model": route_target,
        "route_action": model_route.get("action"),
        "route_pricing_basis": model_route.get("pricing_basis"),
        "route_projected_savings_fraction": model_route.get(
            "projected_savings_fraction"
        ),
        "route_projected_selected_cost_usd": model_route.get(
            "projected_selected_cost_usd"
        ),
        "route_calibration_applied": model_route.get("calibration_applied"),
        "route_calibration_source": model_route.get("calibration_source"),
        **usage,
        "route_matched_actual": (
            route_target in usage["models"]
            if route_target is not None and usage["usage_available"]
            else None
        ),
        "budget_utilization": utilization,
        "target_met": (
            output_tokens <= budget
            if usage["usage_available"] and budget is not None
            else None
        ),
        "task_success": None,
        "quality_verified": False,
    }
    _locked_append(telemetry_path(root), record)

    def mutate(data: dict) -> None:
        data.pop("output_telemetry_pending", None)

    update_state(root, mutate, session_id)
    return record


def load_output_telemetry_from_state(state_root: Path) -> list[dict]:
    """Load valid telemetry records from an explicit Token Saver state directory."""
    telemetry_dir = state_root / "telemetry"
    if not telemetry_dir.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("schema") == TELEMETRY_SCHEMA:
                records.append(item)
    return records


def load_output_telemetry(root: Path) -> list[dict]:
    """Load valid project telemetry records, skipping malformed JSONL rows."""
    path = telemetry_path(root)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records: list[dict] = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("schema") == TELEMETRY_SCHEMA:
            records.append(item)
    return records


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile for a numeric sample."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _number(value: object) -> float:
    """Return a finite nonnegative number or zero for malformed telemetry."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    numeric = float(value)
    return numeric if math.isfinite(numeric) and numeric >= 0 else 0.0


def _positive_budget(record: dict) -> float | None:
    """Return one valid selected budget from a telemetry record."""
    value = record.get("selected_budget")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def _group_summary(records: list[dict]) -> dict:
    """Summarize measured budget effectiveness for one telemetry group."""
    measured = [record for record in records if record.get("usage_available")]
    with_budget = [
        (record, budget)
        for record in measured
        if (budget := _positive_budget(record)) is not None
    ]
    outputs = [_number(record.get("output_tokens")) for record in measured]
    inputs = [_number(record.get("input_tokens")) for record in measured]
    cache_created = [
        _number(record.get("cache_creation_input_tokens")) for record in measured
    ]
    cache_read = [
        _number(record.get("cache_read_input_tokens")) for record in measured
    ]
    cache_created_5m = [
        _number(record.get("cache_creation_5m_input_tokens")) for record in measured
    ]
    cache_created_1h = [
        _number(record.get("cache_creation_1h_input_tokens")) for record in measured
    ]
    budgets = [budget for _record, budget in with_budget]
    utilizations = [
        _number(record.get("budget_utilization"))
        for record, _budget in with_budget
        if isinstance(record.get("budget_utilization"), (int, float))
        and not isinstance(record.get("budget_utilization"), bool)
        and math.isfinite(float(record["budget_utilization"]))
        and float(record["budget_utilization"]) >= 0
    ]
    target_hits = [record.get("target_met") is True for record, _budget in with_budget]
    return {
        "turns": len(records),
        "measured_turns": len(measured),
        "completed_turns": sum(record.get("turn_status") == "completed" for record in records),
        "api_failures": sum(record.get("turn_status") == "api_failure" for record in records),
        "input_tokens": int(sum(inputs)),
        "cache_creation_input_tokens": int(sum(cache_created)),
        "cache_read_input_tokens": int(sum(cache_read)),
        "cache_creation_5m_input_tokens": int(sum(cache_created_5m)),
        "cache_creation_1h_input_tokens": int(sum(cache_created_1h)),
        "output_tokens": int(sum(outputs)),
        "model_calls": int(sum(_number(record.get("model_calls")) for record in measured)),
        "mean_output_tokens": (sum(outputs) / len(outputs) if outputs else None),
        "p90_output_tokens": _percentile(outputs, 0.90),
        "mean_selected_budget": (sum(budgets) / len(budgets) if budgets else None),
        "mean_budget_utilization": (
            sum(utilizations) / len(utilizations) if utilizations else None
        ),
        "p50_budget_utilization": _percentile(utilizations, 0.50),
        "p90_budget_utilization": _percentile(utilizations, 0.90),
        "target_met_rate": (
            sum(target_hits) / len(target_hits) if target_hits else None
        ),
    }


def _routing_summary(records: list[dict]) -> dict:
    """Summarize route-target adoption without inferring quality or success."""
    routed = [
        record
        for record in records
        if isinstance(record.get("route_target_model"), str)
        and record["route_target_model"]
    ]
    measured = [
        record
        for record in routed
        if isinstance(record.get("route_matched_actual"), bool)
    ]
    matched = sum(record.get("route_matched_actual") is True for record in measured)
    calibrated = sum(
        record.get("route_calibration_applied") is True for record in routed
    )
    projected_savings = [
        float(record["route_projected_savings_fraction"])
        for record in routed
        if isinstance(record.get("route_projected_savings_fraction"), (int, float))
        and not isinstance(record.get("route_projected_savings_fraction"), bool)
        and math.isfinite(float(record["route_projected_savings_fraction"]))
        and 0 <= float(record["route_projected_savings_fraction"]) <= 1
    ]
    targets: dict[str, int] = defaultdict(int)
    actions: dict[str, int] = defaultdict(int)
    for record in routed:
        targets[str(record["route_target_model"])] += 1
        action = record.get("route_action")
        if isinstance(action, str) and action:
            actions[action] += 1
    return {
        "decisions": len(routed),
        "measured_actual_turns": len(measured),
        "matched_actual_turns": matched,
        "calibrated_decisions": calibrated,
        "calibrated_decision_rate": (
            calibrated / len(routed) if routed else None
        ),
        "match_rate": matched / len(measured) if measured else None,
        "mean_projected_savings_fraction": (
            sum(projected_savings) / len(projected_savings)
            if projected_savings
            else None
        ),
        "projected_savings_samples": len(projected_savings),
        "targets": dict(sorted(targets.items())),
        "actions": dict(sorted(actions.items())),
        "observational_only": True,
    }


def output_telemetry_report(
    root: Path,
    *,
    since: int | None = None,
) -> dict:
    """Aggregate local telemetry without inferring task success or quality."""
    records = load_output_telemetry(root)
    if since is not None:
        records = [
            record
            for record in records
            if isinstance(record.get("recorded_at"), int)
            and record["recorded_at"] >= since
        ]
    by_task_mode: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        task = str(record.get("task") or "unknown")
        mode = str(record.get("mode") or "unknown")
        by_task_mode[f"{task}:{mode}"].append(record)

    groups = {
        key: _group_summary(group)
        for key, group in sorted(by_task_mode.items())
    }
    underused: list[str] = []
    overruns: list[str] = []
    for key, summary in groups.items():
        if summary["measured_turns"] < 5:
            continue
        utilization = summary["p90_budget_utilization"]
        if utilization is not None and utilization <= 0.60:
            underused.append(key)
        target_rate = summary["target_met_rate"]
        if target_rate is not None and target_rate < 0.80:
            overruns.append(key)

    return {
        "schema": TELEMETRY_SCHEMA,
        "path": str(telemetry_path(root)),
        "summary": _group_summary(records),
        "routing": _routing_summary(records),
        "by_task_mode": groups,
        "signals": {
            "underused_budget_groups": underused,
            "frequent_target_overrun_groups": overruns,
            "minimum_turns": 5,
            "observational_only": True,
        },
        "evidence_limits": {
            "task_success_evidence": False,
            "quality_evidence": False,
            "note": (
                "Stop means the model turn completed; it does not prove the coding "
                "task succeeded or that response quality was preserved."
            ),
        },
    }

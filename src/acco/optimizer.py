"""Closed-loop local optimization proposals with measured keep/revert decisions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from .efficiency.advisor import advisor_report
from .output_telemetry import load_output_telemetry
from .recovery import RecoveryStore
from .runtime_config import find_project_config, settings_for
from .state import state_dir

_SECTION_RE = re.compile(r"^\s*\[([^]]+)]\s*$")


@dataclass(frozen=True)
class OptimizationProposal:
    """One reversible ACCO-owned configuration optimization."""

    id: str
    title: str
    rationale: str
    section: str
    key: str
    value: Any
    risk: str = "low"

    def to_dict(self) -> dict:
        """Return JSON-safe proposal metadata."""
        return asdict(self)


def _project_id(root: Path) -> str:
    """Return an opaque project identity for optimization journals."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def _journal_dir(root: Path) -> Path:
    """Return private optimization journal directory."""
    return state_dir() / "optimizer" / _project_id(root)


def _mean_measured_tokens(
    root: Path,
    *,
    since: int | None = None,
    until: int | None = None,
) -> tuple[float | None, int]:
    """Return provider-reported mean token units per measured turn."""
    totals: list[int] = []
    for record in load_output_telemetry(root):
        at = record.get("recorded_at")
        if not isinstance(at, int):
            continue
        if since is not None and at < since:
            continue
        if until is not None and at >= until:
            continue
        if not record.get("usage_available"):
            continue
        total = 0
        for field in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        ):
            value = record.get(field, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                total += int(value)
        totals.append(total)
    return (sum(totals) / len(totals), len(totals)) if totals else (None, 0)


def propose_optimizations(root: Path, *, days: int = 7) -> dict:
    """Build safe config proposals from current measured/project configuration."""
    root = root.resolve()
    settings = settings_for(root)
    advisor = advisor_report(root, days=days, user_scope=True)
    proposals: list[OptimizationProposal] = []

    if settings.mcp_profile == "full":
        proposals.append(
            OptimizationProposal(
                id="adaptive-mcp",
                title="Use adaptive MCP tool disclosure",
                rationale=(
                    "Start with a bounded tool surface and expand by task instead "
                    "of advertising the full schema on every MCP session."
                ),
                section="mcp",
                key="profile",
                value="adaptive",
            )
        )
    if not settings.mcp_compress_schemas:
        proposals.append(
            OptimizationProposal(
                id="compress-mcp-schemas",
                title="Compress selected MCP schemas",
                rationale=(
                    "Drop annotation-only schema metadata and shorten long "
                    "descriptions while preserving construction constraints; "
                    "the exact catalog is stored in recovery."
                ),
                section="mcp",
                key="compress_schemas",
                value=True,
            )
        )

    recommendations = {
        item.get("id"): item
        for item in advisor.get("recommendations", [])
        if isinstance(item, dict)
    }
    if (
        "inspect-cache-stability" in recommendations
        and not settings.prefix_tracking
    ):
        proposals.append(
            OptimizationProposal(
                id="track-provider-prefix",
                title="Track stable provider prefixes",
                rationale=(
                    "Record content-free prefix fingerprints and cache reuse "
                    "signals so later rewrites can be judged against cache churn."
                ),
                section="provider",
                key="prefix_tracking",
                value=True,
            )
        )

    return {
        "schema": 1,
        "root": str(root),
        "window_days": days,
        "proposals": [item.to_dict() for item in proposals],
        "advisor_recommendations": advisor.get("recommendations", []),
        "evidence": {
            "measured": "provider-reported usage is used when available",
            "not_claimed": "a proposal is not a savings claim until a post-change evaluation",
        },
    }


def _toml_value(value: Any) -> str:
    """Render the small scalar subset used by optimizer-owned config edits."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return json.dumps(str(value))


def _set_toml_scalar(text: str, section: str, key: str, value: Any) -> str:
    """Set one scalar key while preserving unrelated user configuration text."""
    lines = text.splitlines()
    section_start: int | None = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if not match:
            continue
        name = match.group(1).strip()
        if section_start is not None:
            section_end = index
            break
        if name == section:
            section_start = index
    rendered = f"{key} = {_toml_value(value)}"
    if section_start is None:
        suffix = "" if not lines or not lines[-1].strip() else ""
        addition = [f"[{section}]", rendered]
        return "\n".join([*lines, *([suffix] if suffix else []), *addition]).rstrip() + "\n"

    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for index in range(section_start + 1, section_end):
        if key_re.match(lines[index]):
            lines[index] = rendered
            return "\n".join(lines) + "\n"
    lines.insert(section_end, rendered)
    return "\n".join(lines) + "\n"


def _proposal_by_id(root: Path, proposal_id: str, days: int) -> OptimizationProposal:
    """Resolve one currently applicable proposal."""
    report = propose_optimizations(root, days=days)
    for raw in report["proposals"]:
        if raw["id"] == proposal_id:
            return OptimizationProposal(**raw)
    raise ValueError(f"optimization proposal is not currently applicable: {proposal_id}")


def apply_optimization(
    root: Path,
    proposal_id: str,
    *,
    days: int = 7,
) -> dict:
    """Apply one reversible ACCO config proposal and journal its baseline."""
    root = root.resolve()
    proposal = _proposal_by_id(root, proposal_id, days)
    config_path = find_project_config(root) or (root / ".acco.toml")
    original = config_path.read_bytes() if config_path.exists() else b""
    recovery = RecoveryStore(root)
    recovery_handle = recovery.put(
        original,
        content_type="text/toml",
        metadata={"transform": "optimizer-config-backup", "path": str(config_path)},
    )
    baseline_mean, baseline_turns = _mean_measured_tokens(
        root,
        since=int(time.time()) - days * 86400,
    )
    before_text = original.decode("utf-8") if original else ""
    updated = _set_toml_scalar(
        before_text,
        proposal.section,
        proposal.key,
        proposal.value,
    )
    config_path.write_text(updated, encoding="utf-8")

    applied_at = int(time.time())
    run_id = "opt_" + hashlib.sha256(
        f"{root}\0{proposal.id}\0{applied_at}".encode()
    ).hexdigest()[:16]
    record = {
        "schema": 1,
        "id": run_id,
        "proposal": proposal.to_dict(),
        "config_path": str(config_path),
        "recovery_handle": recovery_handle,
        "baseline_mean_tokens_per_turn": baseline_mean,
        "baseline_turns": baseline_turns,
        "applied_at": applied_at,
        "status": "active",
    }
    directory = _journal_dir(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / f"{run_id}.json").write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )
    return record


def evaluate_optimization(
    root: Path,
    run_id: str,
    *,
    min_turns: int = 5,
    min_improvement: float = 0.0,
    revert_on_no_gain: bool = True,
) -> dict:
    """Keep or revert one applied optimization using post-change measured turns."""
    if min_turns <= 0:
        raise ValueError("optimizer min_turns must be positive")
    if not 0 <= min_improvement < 1:
        raise ValueError("optimizer min_improvement must be in [0, 1)")
    root = root.resolve()
    path = _journal_dir(root) / f"{run_id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("status") != "active":
        raise ValueError(f"optimization run is not active: {run_id}")

    after_mean, after_turns = _mean_measured_tokens(
        root,
        since=int(record["applied_at"]),
    )
    baseline = record.get("baseline_mean_tokens_per_turn")
    if baseline is None or int(record.get("baseline_turns", 0)) < min_turns:
        decision = "insufficient-baseline"
        improved = None
    elif after_mean is None or after_turns < min_turns:
        decision = "insufficient-treatment"
        improved = None
    else:
        threshold = float(baseline) * (1.0 - min_improvement)
        improved = float(after_mean) < threshold
        decision = "keep" if improved else "revert"

    reverted = False
    if decision == "revert" and revert_on_no_gain:
        recovery = RecoveryStore(root)
        original = recovery.get(str(record["recovery_handle"])).payload
        config_path = Path(record["config_path"])
        if original:
            config_path.write_bytes(original)
        elif config_path.exists():
            config_path.unlink()
        reverted = True

    record.update(
        evaluated_at=int(time.time()),
        treatment_mean_tokens_per_turn=after_mean,
        treatment_turns=after_turns,
        min_improvement=min_improvement,
        decision=decision,
        reverted=reverted,
        status="reverted" if reverted else "kept" if decision == "keep" else "active",
    )
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def optimization_status(root: Path) -> list[dict]:
    """Return optimization journal metadata without recovered config contents."""
    directory = _journal_dir(root.resolve())
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("opt_*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            out.append(value)
    return out

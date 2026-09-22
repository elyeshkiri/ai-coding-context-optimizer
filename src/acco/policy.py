"""Conservative session-lifecycle suggestions based on observed usage.

Hooks cannot type /clear. This module writes a tiny snapshot the hook can
read in milliseconds, and a short reminder only when there are tokens at stake.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .sessions import Report, Turn
from .state import load as load_state
from .state import update as update_state

DEFAULT_CACHE_TTL_MIN = 5
COMPACT_TURNS = 24
LONG_SESSION_TURNS = 40
REMINDER_CHARS = 320


def cache_ttl_min() -> int:
    """Handle cache ttl min."""
    raw = os.environ.get("TOKEN_SAVER_CACHE_TTL_MIN")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_CACHE_TTL_MIN


def _parse_ts(raw: str | None) -> datetime | None:
    """Parse ts."""
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def idle_gaps(turns: list[Turn], minutes: int | None = None) -> list[tuple[Turn, Turn, float]]:
    """Handle idle gaps."""
    threshold = cache_ttl_min() if minutes is None else minutes
    by_session: dict[str, list[Turn]] = {}
    for turn in turns:
        by_session.setdefault(turn.session, []).append(turn)
    gaps: list[tuple[Turn, Turn, float]] = []
    for group in by_session.values():
        ordered = sorted(group, key=lambda t: t.timestamp or "")
        prev = None
        for turn in ordered:
            ts = _parse_ts(turn.timestamp)
            if prev is not None and ts is not None:
                prev_ts = _parse_ts(prev.timestamp)
                if prev_ts is not None:
                    delta = (ts - prev_ts).total_seconds() / 60.0
                    if delta >= threshold:
                        gaps.append((prev, turn, delta))
            prev = turn
    gaps.sort(key=lambda row: -row[2])
    return gaps


@dataclass
class Advice:
    """Represent advice state and behavior."""
    kind: str
    detail: str
    tokens_at_stake: int = 0


def advise(report: Report) -> list[Advice]:
    """Handle advise."""
    out: list[Advice] = []
    churn, churn_turns, _worst = report.cache_churn()
    if churn:
        out.append(
            Advice(
                "clear",
                f"{churn_turns} suspected prefix recreations (~{churn:,} overlapping tokens; not proven waste). "
                "/clear between unrelated tasks.",
                tokens_at_stake=churn,
            )
        )
    ttl = cache_ttl_min()
    gaps = idle_gaps(report.turns, minutes=ttl)
    if gaps:
        worst = gaps[0][2]
        out.append(
            Advice(
                "idle",
                f"{len(gaps)} gaps ≥{ttl} min assumed TTL (worst {worst:.0f} min); expiry unverified.",
                tokens_at_stake=0,
            )
        )
    by_session: dict[str, int] = {}
    for turn in report.turns:
        by_session[turn.session] = by_session.get(turn.session, 0) + 1
    long_ones = [n for n in by_session.values() if n >= LONG_SESSION_TURNS]
    if long_ones:
        out.append(
            Advice(
                "compact",
                f"{len(long_ones)} sessions ≥{LONG_SESSION_TURNS} turns. "
                f"/compact Keep: plan, files, open errors near {COMPACT_TURNS} turns.",
            )
        )
    tool_tokens = sum(c.tokens for c in report.calls)
    if report.fresh_input and tool_tokens / report.fresh_input >= 0.08:
        out.append(
            Advice(
                "filter",
                f"estimated one-copy tool output / fresh-input ratio is {100 * tool_tokens / report.fresh_input:.1f}%; not a bill share.",
                tokens_at_stake=tool_tokens,
            )
        )
    wasted = sum(row[2] for row in report.duplicate_reads())
    if wasted:
        out.append(
            Advice(
                "reread",
                f"~{wasted:,} tokens in repeated reads within a context epoch; necessity unknown.",
                tokens_at_stake=wasted,
            )
        )
    if not out:
        out.append(Advice("ok", "No large lifecycle candidate detected by these heuristics."))
    return out


def reminder(report: Report, limit: int = REMINDER_CHARS) -> str:
    """Stored diagnostic summary; no confirmed savings are implied."""
    items = [a for a in advise(report) if a.kind != "ok" and a.tokens_at_stake > 0]
    if not items:
        return ""
    top = items[0]
    text = f"token-saver: {top.kind} — {top.detail} Type /clear if this is a new task."
    return text if len(text) <= limit else text[: limit - 1] + "…"


def snapshot(report: Report, root: Path) -> Path:
    """Return the requested value."""
    items = advise(report)
    fields = {}
    data = fields
    data["advice"] = [
        {"kind": a.kind, "detail": a.detail, "tokens_at_stake": a.tokens_at_stake}
        for a in items
        if a.kind != "ok"
    ]
    data["fresh_input"] = report.fresh_input
    churn_tokens, churn_turns, _ = report.cache_churn()
    data["churn_tokens"] = churn_tokens
    data["churn_turns"] = churn_turns
    data["sessions"] = report.sessions
    data["reminder"] = reminder(report)
    return update_state(root, lambda current: current.update(fields))


NEW_TASK_HINTS = (
    "new task",
    "different task",
    "unrelated",
    "start over",
    "switch to",
    "ignore previous",
    "from scratch",
)


def looks_like_new_task(prompt: str) -> bool:
    """Return whether looks like new task."""
    low = prompt.lower()
    return any(hint in low for hint in NEW_TASK_HINTS)


def user_nudge(root: Path, prompt: str = "") -> str:
    """One line for the user (stderr). Empty if nothing at stake or not a switch."""
    data = load_state(root)
    churn = int(data.get("churn_tokens") or 0)
    if churn <= 0 or not looks_like_new_task(prompt):
        return ""
    return (
        f"token-saver: if unrelated, consider /clear to remove "
        f"unneeded history (~{churn:,} tokens in suspected recreations last measure)."
    )


SKILL_TEXT = """---
name: token-budget
description: Session hygiene when context is fat or the user starts a new task. Do not load unless asked or a new task starts.
---

# Token budget (on demand)

- New task → `/clear`. Same task, history noisy → `/compact Keep: plan, files, open errors`.
- Cache TTL depends on configuration. An idle gap alone does not prove wasted tokens.
- Never clear necessary history merely to chase a cache heuristic.
- Read source with offset/limit after an outline.
- Never paste raw test or install logs.
- For final responses: result first; no conversational preamble, task restatement, tool narration, recap, or closing filler.
- Preserve required code, diagnostics, safety caveats, and explicit user output formats even when they exceed the preferred budget.
- When a cause is not proven, label it as a hypothesis instead of spending tokens on a confident guess.
"""


def write_skill(root: Path) -> Path:
    """Write skill."""
    dest = root / ".claude" / "skills" / "token-budget" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(SKILL_TEXT, encoding="utf-8")
    return dest

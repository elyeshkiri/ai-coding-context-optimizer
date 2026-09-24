"""Historical session analysis for ranking ACCO optimization opportunities."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import time

from .audit import audit
from .session_metrics import transcript_session_metrics
from .sessions import analyze, transcript_paths


def _recent_paths(root: Path, days: int) -> list[Path]:
    """Return project Claude transcripts modified inside the requested window."""
    cutoff = time.time() - days * 86400
    paths: list[Path] = []
    for path in transcript_paths(root):
        try:
            if path.stat().st_mtime >= cutoff:
                paths.append(path)
        except OSError:
            continue
    return paths


def _opportunity(
    ident: str,
    *,
    title: str,
    estimated_tokens: int | None,
    evidence: str,
    action: str,
    caution: str,
) -> dict:
    """Build one explicit learn recommendation."""
    return {
        "id": ident,
        "title": title,
        "estimated_tokens_at_stake": estimated_tokens,
        "evidence": evidence,
        "action": action,
        "caution": caution,
    }


def learn_report(
    root: Path,
    *,
    days: int = 30,
    top: int = 8,
    user_scope: bool = True,
    paths: list[Path] | None = None,
) -> dict:
    """Analyze historical Claude sessions and rank evidence-backed token sinks."""
    if days <= 0:
        raise ValueError("days must be positive")
    if top <= 0:
        raise ValueError("top must be positive")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    selected = list(paths) if paths is not None else _recent_paths(root, days)
    selected = [Path(path) for path in selected if Path(path).is_file()]
    if not selected:
        raise ValueError(
            f"no Claude session transcripts found for {root} in the last {days} days"
        )

    report = analyze(selected, keep_content=True)
    behavior: Counter[str] = Counter()
    for path in selected:
        metrics = transcript_session_metrics(path)
        for field in (
            "tool_calls",
            "bash_calls",
            "repeat_command_calls",
            "retry_attempts",
            "duplicate_read_calls",
        ):
            behavior[field] += int(metrics.get(field) or 0)

    tool_rows = report.by_tool()
    tool_total = sum(tokens for _name, tokens, _calls in tool_rows)
    duplicate_rows = report.duplicate_reads()
    duplicate_tokens = sum(tokens for _path, _count, tokens in duplicate_rows)
    outline_before, outline_after, outline_rows = report.outline_savings()
    outline_reduction = max(0, outline_before - outline_after)
    recreated_tokens, recreated_turns, _worst = report.cache_churn()
    audited = audit(root, user_scope=user_scope)

    turns = len(report.turns)
    output_tokens = int(report.usage["output_tokens"])
    output_per_turn = output_tokens / turns if turns else 0.0

    opportunities: list[dict] = []
    if duplicate_tokens:
        opportunities.append(
            _opportunity(
                "duplicate-reads",
                title="Repeated identical source reads",
                estimated_tokens=duplicate_tokens,
                evidence=(
                    f"{behavior['duplicate_read_calls']} repeated Read call(s) "
                    "inside the same session/context epoch"
                ),
                action=(
                    "Prefer bounded reads, acco pack, remembered exact-read digests, "
                    "or reuse prior evidence before reopening unchanged files."
                ),
                caution=(
                    "Estimated result-size reduction only; a repeated read can be "
                    "necessary and is not automatically waste."
                ),
            )
        )
    if outline_reduction:
        opportunities.append(
            _opportunity(
                "outline-source",
                title="Large source reads that can start from structure",
                estimated_tokens=outline_reduction,
                evidence=(
                    f"{outline_before:,} estimated source-read tokens could have "
                    f"started as about {outline_after:,} outline tokens"
                ),
                action=(
                    "Use acco outline or acco pack first, then request exact line "
                    "ranges for implementation/edit work."
                ),
                caution=(
                    "One-shot hypothetical only; follow-up exact reads are excluded."
                ),
            )
        )
    if tool_total:
        top_tool = tool_rows[0]
        opportunities.append(
            _opportunity(
                "tool-output",
                title=f"Large {top_tool[0]} result volume",
                estimated_tokens=int(top_tool[1]),
                evidence=(
                    f"{top_tool[0]} produced about {top_tool[1]:,} estimated result "
                    f"tokens across {top_tool[2]} call(s)"
                ),
                action=(
                    "Run acco output-explain for noisy commands and keep command-aware "
                    "compression enabled; retrieve exact originals only when needed."
                ),
                caution=(
                    "Tool-result size is not provider billing attribution and cannot "
                    "be read as a savings ceiling."
                ),
            )
        )
    if recreated_tokens:
        opportunities.append(
            _opportunity(
                "cache-recreation",
                title="Suspected prompt-cache recreation",
                estimated_tokens=recreated_tokens,
                evidence=(
                    f"{recreated_tokens:,} provider-reported cache-write tokens across "
                    f"{recreated_turns} suspected recreation turn(s)"
                ),
                action=(
                    "Inspect stable-prefix churn and use acco cache-economics before "
                    "rewriting cached context."
                ),
                caution=(
                    "Heuristic: expiry and legitimate prefix changes cannot be "
                    "distinguished from usage counters alone."
                ),
            )
        )
    if output_per_turn >= 800:
        opportunities.append(
            _opportunity(
                "assistant-output",
                title="High assistant output volume",
                estimated_tokens=output_tokens,
                evidence=(
                    f"{output_tokens:,} provider-reported output tokens across "
                    f"{turns} response(s), average {output_per_turn:,.0f}"
                ),
                action=(
                    "Inspect acco output-policy/output-telemetry and calibrate shorter "
                    "generation budgets only where task quality remains intact."
                ),
                caution=(
                    "Output tokens are measured volume, not proven avoidable tokens."
                ),
            )
        )
    if audited.always_on >= 2_000:
        opportunities.append(
            _opportunity(
                "always-on-context",
                title="Large always-on project instructions",
                estimated_tokens=audited.always_on,
                evidence=(
                    f"{audited.always_on:,} current always-on tokens are loaded by "
                    "the configured instruction surface"
                ),
                action=(
                    "Run acco audit and move infrequently needed guidance to scoped "
                    "rules or on-demand context."
                ),
                caution=(
                    "Static context size is not multiplied into billed cost here "
                    "because prompt-cache behavior varies."
                ),
            )
        )
    if behavior["retry_attempts"]:
        opportunities.append(
            _opportunity(
                "retry-loops",
                title="Repeated identical failing commands",
                estimated_tokens=None,
                evidence=f"{behavior['retry_attempts']} retry attempt(s) with the same failure fingerprint",
                action=(
                    "Stop blind retries, preserve the failure as evidence, and revisit "
                    "the hypothesis before invoking the same command again."
                ),
                caution="No token amount is assigned because retry result sizes vary.",
            )
        )

    opportunities.sort(
        key=lambda item: (
            item["estimated_tokens_at_stake"] is None,
            -(item["estimated_tokens_at_stake"] or 0),
            item["id"],
        )
    )

    return {
        "schema": 1,
        "root": str(root),
        "window_days": days,
        "sessions": report.sessions,
        "transcripts": len(selected),
        "turns": turns,
        "usage": {
            "input_tokens": int(report.usage["input_tokens"]),
            "cache_creation_input_tokens": int(
                report.usage["cache_creation_input_tokens"]
            ),
            "cache_read_input_tokens": int(
                report.usage["cache_read_input_tokens"]
            ),
            "output_tokens": output_tokens,
            "cache_hit_rate": report.cache_hit_rate,
        },
        "tool_results": {
            "estimated_tokens": tool_total,
            "by_tool": [
                {"tool": name, "estimated_tokens": tokens, "calls": calls}
                for name, tokens, calls in tool_rows[:top]
            ],
            "largest": [
                {
                    "tool": call.name,
                    "estimated_tokens": call.tokens,
                    "label": call.label,
                }
                for call in report.biggest(top)
            ],
        },
        "behavior": dict(behavior),
        "duplicate_reads": {
            "estimated_tokens": duplicate_tokens,
            "rows": [
                {"path": path, "reads": count, "estimated_repeat_tokens": tokens}
                for path, count, tokens in duplicate_rows[:top]
            ],
        },
        "outline": {
            "source_read_tokens": outline_before,
            "outline_tokens": outline_after,
            "estimated_reduction": outline_reduction,
            "rows": [
                {"path": path, "source_tokens": before, "outline_tokens": after}
                for path, before, after in outline_rows[:top]
            ],
        },
        "cache_recreation": {
            "suspected_tokens": recreated_tokens,
            "turns": recreated_turns,
        },
        "always_on": {
            "tokens": audited.always_on,
            "counter": audited.counter_label,
        },
        "opportunities": opportunities[:top],
        "evidence": {
            "provider_usage_measured": True,
            "tool_result_sizes_estimated": True,
            "task_success_verified": False,
            "quality_verified": False,
            "savings_claim": False,
            "privacy": (
                "Local Claude transcripts are read only. The report does not send "
                "session content to a network service."
            ),
        },
    }

"""CLI handlers for session continuity and local efficiency telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..cache_economics import assess_context_rewrite
from ..efficiency import continuity_report, dashboard_report
from ..efficiency.advisor import advisor_report
from ..efficiency.dashboard import render_dashboard_html


def _tokens(value: object) -> str:
    """Format a token count for compact terminal output."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "0"
    number = int(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(number)


def dashboard_main(argv: list[str]) -> int:
    """Show local operational savings, continuity, and waste telemetry."""
    parser = argparse.ArgumentParser(prog="token-saver dashboard")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="write a self-contained local HTML dashboard",
    )
    args = parser.parse_args(argv)
    try:
        report = dashboard_report(Path(args.path), days=args.days)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.html:
        destination = Path(args.html).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            render_dashboard_html(report),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    savings = report["savings"]
    behavior = report["behavior"]
    continuity = report["continuity"]
    usage = report["billed_usage"]
    print(f"TOKEN SAVER DASHBOARD — {report['window_days']} days")
    print(
        "estimated tool-context saved: "
        + _tokens(savings["estimated_tool_context_tokens"])
        + " tokens"
    )
    for feature, tokens in savings["by_feature"].items():
        print(f"  {feature:<22} {_tokens(tokens):>8}")
    print(f"continuity restores: {continuity['restores']}")
    print(f"tracked sessions:    {continuity['tracked_sessions']}")
    print(f"behavior signals:    {behavior['events']}")
    for feature, count in behavior["signals"].items():
        print(f"  {feature:<22} {count:>8}")
    print("billed usage observed:")
    print(f"  input              {_tokens(usage.get('input_tokens')):>8}")
    print(f"  cache creation     {_tokens(usage.get('cache_creation_input_tokens')):>8}")
    print(f"  cache read         {_tokens(usage.get('cache_read_input_tokens')):>8}")
    print(f"  output             {_tokens(usage.get('output_tokens')):>8}")
    print("note: local savings are operational estimates, not a cost/success claim")
    if args.html:
        print(f"html: {Path(args.html).expanduser().resolve()}")
    return 0



def cost_advisor_main(argv: list[str]) -> int:
    """Show measured local cost intelligence and prioritized efficiency actions."""
    parser = argparse.ArgumentParser(prog="token-saver cost-advisor")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--rates",
        help="pricing source: builtin or an explicit exact-model JSON file",
    )
    parser.add_argument(
        "--project-only",
        action="store_true",
        help="exclude user-scope Claude instructions from the context audit",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = advisor_report(
            Path(args.path),
            days=args.days,
            rates_path=(
                args.rates
                if args.rates == "builtin"
                else Path(args.rates)
                if args.rates
                else None
            ),
            user_scope=not args.project_only,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    score = report["score"]
    grade = score["grade"] or "insufficient evidence"
    print(f"TOKEN SAVER COST ADVISOR — {report['window_days']} days")
    print(
        f"efficiency score: {score['percent']:.1f}% ({grade}); "
        f"evidence coverage {score['coverage']:.0%}"
    )
    print(f"always-on context: {_tokens(report['context']['always_on_tokens'])} tokens")
    print(
        "estimated tool-context saved: "
        f"{_tokens(report['savings']['estimated_tool_context_tokens'])} tokens"
    )
    cost = report["cost"]
    if cost["usd"] is not None:
        print(f"observed usage cost: USD {cost['usd']:.4f} (complete)")
    elif cost["priced_usd"] is not None:
        print(
            f"observed usage cost: USD {cost['priced_usd']:.4f} partial "
            f"({cost['priced_turns']}/{cost['measured_turns']} turns priced)"
        )
    else:
        print("observed usage cost: not priced")
    print("score breakdown:")
    for category in score["categories"]:
        if category["available"]:
            print(
                f"  {category['name']:<25} "
                f"{category['score']:>5}/{category['weight']}"
            )
        else:
            print(f"  {category['name']:<25}   n/a  ({category['reason']})")
    print("next actions:")
    if not report["recommendations"]:
        print("  none from current evidence")
    for item in report["recommendations"]:
        print(
            f"  [{item['priority']}] {item['action']} "
            f"— {item['evidence']}"
        )
    print(
        "evidence: measured usage/context is separate from estimated savings; "
        "no task-success or end-to-end cost claim"
    )
    return 0



def continuity_main(argv: list[str]) -> int:
    """Inspect the latest structured continuity checkpoint."""
    parser = argparse.ArgumentParser(prog="token-saver continuity")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = continuity_report(Path(args.path))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("TOKEN SAVER CONTINUITY")
    if not report["available"]:
        print("checkpoint: none")
        return 0
    print(f"task: {report['task'] or 'general'}")
    files = [
        item.get("path")
        for item in report["working_files"]
        if isinstance(item, dict) and item.get("path")
    ]
    print("working files: " + (", ".join(files) if files else "none"))
    validations = [
        f"{item.get('kind')}={item.get('status')}"
        for item in report["validations"]
        if isinstance(item, dict)
    ]
    print("validation: " + ("; ".join(validations) if validations else "none"))
    failures = [
        str(item.get("label"))
        for item in report["failures"]
        if isinstance(item, dict) and item.get("label")
    ]
    print("recent failures: " + ("; ".join(failures) if failures else "none"))
    return 0



def cache_economics_main(argv: list[str]) -> int:
    """Estimate whether one context rewrite is cheaper after cache effects."""
    parser = argparse.ArgumentParser(prog="token-saver cache-economics")
    parser.add_argument("--original-frontier-tokens", type=int, required=True)
    parser.add_argument("--replacement-frontier-tokens", type=int, required=True)
    parser.add_argument("--cached-prefix-tokens", type=int, default=0)
    parser.add_argument("--invalidates-cached-prefix", action="store_true")
    parser.add_argument("--expected-reuses", type=int, default=1)
    parser.add_argument("--cache-write-factor", type=float, default=1.25)
    parser.add_argument("--cache-read-factor", type=float, default=0.10)
    parser.add_argument("--min-relative-savings", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        decision = assess_context_rewrite(
            original_frontier_tokens=args.original_frontier_tokens,
            replacement_frontier_tokens=args.replacement_frontier_tokens,
            cached_prefix_tokens=args.cached_prefix_tokens,
            invalidates_cached_prefix=args.invalidates_cached_prefix,
            expected_reuses=args.expected_reuses,
            cache_write_factor=args.cache_write_factor,
            cache_read_factor=args.cache_read_factor,
            min_relative_savings=args.min_relative_savings,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = decision.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    verdict = "ACCEPT" if decision.accepted else "PRESERVE"
    print(f"CACHE ECONOMICS: {verdict}")
    print(f"original relative cost:    {decision.original_cost:.2f}")
    print(f"replacement relative cost: {decision.replacement_cost:.2f}")
    if decision.relative_savings is not None:
        print(f"relative savings:          {decision.relative_savings:.2%}")
    print(
        "cached prefix: "
        f"{decision.cached_prefix_tokens} tokens; "
        f"invalidated={decision.invalidates_cached_prefix}"
    )
    return 0

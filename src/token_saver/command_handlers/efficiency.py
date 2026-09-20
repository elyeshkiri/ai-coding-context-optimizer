"""CLI handlers for session continuity and local efficiency telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..efficiency import continuity_report, dashboard_report


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
    args = parser.parse_args(argv)
    try:
        report = dashboard_report(Path(args.path), days=args.days)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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

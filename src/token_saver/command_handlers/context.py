"""Repository context, navigation, and feedback CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..context_browser import browse_context
from ..feedback import record_feedback
from ..impact import analyze_impact


def impact_main(argv: list[str]) -> int:
    """Run the impact command."""
    parser = argparse.ArgumentParser(prog="token-saver impact")
    parser.add_argument("target", help="repository-relative file or symbol name")
    parser.add_argument("--path", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = analyze_impact(Path(args.path).resolve(), args.target)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"IMPACT: {args.target}")
        for match in payload["matched"]:
            suffix = f":{match['start_line']}" if match["start_line"] else ""
            print(f"= {match['path']}{suffix} {match['symbol'] or ''}".rstrip())
        for item in report.affected:
            symbol = f"::{item.symbol}" if item.symbol else ""
            print(f"{item.confidence:.2f} {item.path}{symbol} [{item.reason}]")
    return 0


def feedback_main(argv: list[str]) -> int:
    """Run the feedback command."""
    parser = argparse.ArgumentParser(prog="token-saver feedback")
    parser.add_argument("file")
    parser.add_argument("--path", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--useful", action="store_true")
    group.add_argument("--irrelevant", action="store_true")
    args = parser.parse_args(argv)
    scores = record_feedback(Path(args.path), args.file, useful=args.useful)
    normalized = args.file.replace("\\", "/").lstrip("./")
    print(json.dumps({"file": args.file, "score": scores[normalized]}))
    return 0


def browse_main(argv: list[str]) -> int:
    """Run the browse command."""
    parser = argparse.ArgumentParser(prog="token-saver browse")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--preview-tokens", type=int, default=350)
    parser.add_argument("--detail-tokens", type=int, default=1200)
    parser.add_argument("--show", type=int, help="print one candidate's detailed source view")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-changed-boost", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = browse_context(
            Path(args.path).resolve(),
            args.query,
            max_files=args.max_files,
            preview_tokens=args.preview_tokens,
            detail_tokens=args.detail_tokens,
            changed_boost=not args.no_changed_boost,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    def print_list() -> None:
        """Print ranked context-browser candidates."""
        print(f"CONTEXT BROWSER: {report['query']}")
        for item in report["files"]:
            symbols = ", ".join(
                label.split(":", 1)[-1].rsplit("@", 1)[0]
                for label in item["symbols"]
            ) or "-"
            fuzzy = ", ".join(
                f"{source}->{value['term']} ({value['similarity']:.2f})"
                for source, value in item["fuzzy_corrections"].items()
            )
            suffix = f" fuzzy=[{fuzzy}]" if fuzzy else ""
            print(
                f"{item['rank']:>2}. {item['score']:>7.2f} {item['path']} "
                f"symbols=[{symbols}] tokens~{item['preview_tokens']}{suffix}"
            )

    print_list()
    if args.show is not None:
        if args.show < 1 or args.show > len(report["files"]):
            print("candidate number out of range", file=sys.stderr)
            return 2
        print()
        print(report["files"][args.show - 1]["detail"], end="")

    if args.interactive:
        while True:
            try:
                command = input("browse> ").strip()
            except EOFError:
                break
            if command in {"q", "quit", "exit"}:
                break
            if command in {"", "list", "ls"}:
                print_list()
                continue
            parts = command.split()
            if len(parts) == 2 and parts[0] in {"show", "s"} and parts[1].isdigit():
                selected = int(parts[1])
                if 1 <= selected <= len(report["files"]):
                    print(report["files"][selected - 1]["detail"], end="")
                else:
                    print("candidate number out of range")
                continue
            print("commands: list | show N | quit")
    return 0

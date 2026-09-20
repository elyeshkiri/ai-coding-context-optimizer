"""Repository context, navigation, and feedback CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..repository_service import RepositoryContextService


def impact_main(argv: list[str]) -> int:
    """Run the impact command."""
    parser = argparse.ArgumentParser(prog="token-saver impact")
    parser.add_argument("target", help="repository-relative file or symbol name")
    parser.add_argument("--path", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = RepositoryContextService(Path(args.path)).impact(args.target)
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
    scores = RepositoryContextService(Path(args.path)).feedback(
        args.file,
        useful=args.useful,
    )
    normalized = args.file.replace("\\", "/").lstrip("./")
    print(json.dumps({"file": args.file, "score": scores[normalized]}))
    return 0


def ranking_explain_main(argv: list[str]) -> int:
    """Run the ranking explanation command."""
    parser = argparse.ArgumentParser(prog="token-saver ranking-explain")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-changed-boost", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = RepositoryContextService(Path(args.path)).explain_ranking(
            args.query,
            max_files=args.max_files,
            changed_boost=not args.no_changed_boost,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"RANKING EXPLANATION: {report['query']}")
    for item in report["results"]:
        print(f"{item['rank']:>2}. {item['final_score']:>9.3f} {item['path']}")
        for event in item["trace"]:
            evidence = ", ".join(event["evidence"])
            suffix = f" [{evidence}]" if evidence else ""
            print(
                f"    {event['stage']:<24} "
                f"{event['delta']:+9.3f} -> {event['after']:>9.3f}{suffix}"
            )
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
        report = RepositoryContextService(Path(args.path)).browse(
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



def remember_main(argv: list[str]) -> int:
    """Persist one explicit evidence-backed project finding."""
    parser = argparse.ArgumentParser(prog="token-saver remember")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--claim", required=True)
    parser.add_argument("--anchor", action="append", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--applicability", required=True)
    parser.add_argument(
        "--confidence",
        choices=["speculative", "probable", "verified"],
        default="verified",
    )
    parser.add_argument("--invalidator", action="append")
    parser.add_argument("--supersedes", action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = RepositoryContextService(Path(args.path)).remember_finding(
            claim=args.claim,
            anchors=args.anchor,
            evidence=args.evidence,
            applicability=args.applicability,
            confidence=args.confidence,
            invalidators=args.invalidator,
            supersedes=args.supersedes,
            source="cli",
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"REMEMBERED {result['id']} [{result['confidence']}]")
        print(result["claim"])
        for anchor in result["anchors"]:
            symbol = f"::{anchor['symbol']}" if anchor.get("symbol") else ""
            print(f"- {anchor['path']}{symbol}")
    return 0


def recall_main(argv: list[str]) -> int:
    """Recall durable project findings relevant to one query."""
    parser = argparse.ArgumentParser(prog="token-saver recall")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        findings = RepositoryContextService(Path(args.path)).recall_findings(
            args.query,
            limit=args.limit,
            include_stale=args.include_stale,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(findings, indent=2))
        return 0
    print(f"PROJECT KNOWLEDGE: {args.query}")
    if not findings:
        print("no matching current findings")
        return 0
    for item in findings:
        print(
            f"{item['score']:>5.2f} {item['id']} "
            f"[{item['confidence']}/{item['state']}] {item['claim']}"
        )
        for anchor in item["anchors"]:
            symbol = f"::{anchor['symbol']}" if anchor.get("symbol") else ""
            print(f"    {anchor['path']}{symbol}")
        if item["stale_reasons"]:
            print("    stale: " + ", ".join(item["stale_reasons"]))
    return 0


def knowledge_status_main(argv: list[str]) -> int:
    """Report durable project-knowledge counts and local storage path."""
    parser = argparse.ArgumentParser(prog="token-saver knowledge-status")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = RepositoryContextService(Path(args.path)).knowledge_status()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PROJECT KNOWLEDGE")
        print(
            f"total={result['total']} active={result['active']} "
            f"stale={result['stale']} superseded={result['superseded']}"
        )
        print(result["path"])
    return 0

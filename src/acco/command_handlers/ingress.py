"""CLI handlers for safe oversized-prompt staging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ingress import load_stage, read_stage


def ingress_show_main(argv: list[str]) -> int:
    """Print one bounded staged-prompt packet for agent consumption."""
    parser = argparse.ArgumentParser(prog="acco ingress-show")
    parser.add_argument("id")
    parser.add_argument("--path", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        stage = load_stage(Path(args.path), args.id)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(stage.to_dict(), indent=2))
    else:
        print(stage.packet)
    return 0


def ingress_read_main(argv: list[str]) -> int:
    """Print an exact line range from the locally staged original prompt."""
    parser = argparse.ArgumentParser(prog="acco ingress-read")
    parser.add_argument("id")
    parser.add_argument("--path", default=".")
    parser.add_argument("--start-line", type=int, required=True)
    parser.add_argument("--end-line", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        text = read_stage(
            Path(args.path),
            args.id,
            start_line=args.start_line,
            end_line=args.end_line,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0

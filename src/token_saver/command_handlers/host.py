"""Host integration CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..host_validate import validate_host
from ..serve import serve


def host_check_main(argv: list[str]) -> int:
    """Run the host check command."""
    parser = argparse.ArgumentParser(prog="token-saver host-check")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--host", default="claude", help="host executable to inspect")
    parser.add_argument(
        "--live-evidence",
        help="host debug transcript proving updatedToolOutput acceptance",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return nonzero unless hooks are configured and transport recovery passes",
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="return nonzero unless supplied host debug evidence verifies replacement acceptance",
    )
    args = parser.parse_args(argv)
    try:
        result = validate_host(
            Path(args.path),
            executable=args.host,
            live_evidence=Path(args.live_evidence) if args.live_evidence else None,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    if args.require_live and not result["live_verified"]:
        return 1
    if args.require_ready and not result["ready"]:
        return 1
    return 0


def serve_main(argv: list[str]) -> int:
    """Run the serve command."""
    parser = argparse.ArgumentParser(prog="token-saver serve")
    parser.add_argument("path", nargs="?", default=".")
    args = parser.parse_args(argv)
    return serve(Path(args.path).resolve())

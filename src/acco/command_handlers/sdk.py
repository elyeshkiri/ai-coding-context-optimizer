"""CLI handler for the local ACCO SDK bridge."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ..sdk_server import SdkServerConfig, run_sdk_server


def sdk_serve_main(argv: list[str]) -> int:
    """Run the loopback SDK service for TypeScript and other non-Python agents."""
    parser = argparse.ArgumentParser(prog="acco sdk-serve")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="allow non-loopback binding; put the service behind your own auth",
    )
    parser.add_argument(
        "--recovery-capacity-mb",
        type=int,
        default=512,
        help="exact-recovery storage capacity in MiB",
    )
    args = parser.parse_args(argv)
    if args.recovery_capacity_mb <= 0:
        print("recovery capacity must be positive", file=sys.stderr)
        return 2
    try:
        config = SdkServerConfig(
            root=Path(args.path),
            bind=args.bind,
            port=args.port,
            allow_non_loopback=args.allow_non_loopback,
            recovery_capacity_bytes=args.recovery_capacity_mb * 1024 * 1024,
        ).validate()
        print(
            f"ACCO SDK listening on http://{config.bind}:{config.port} "
            f"for {config.root}",
            file=sys.stderr,
        )
        run_sdk_server(config)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0

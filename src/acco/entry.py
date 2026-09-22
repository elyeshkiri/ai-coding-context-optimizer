"""Stable top-level command dispatcher.

Command registration lives in :mod:`token_saver.command_registry`; this module
owns only argv acquisition and fallback to the mature legacy CLI.
"""

from __future__ import annotations

import sys

from .cli import LEGACY_COMMANDS, main as legacy_main
from .command_registry import DEFAULT_COMMAND_REGISTRY


def _print_help() -> None:
    """Print one merged command index across registry and compatibility surfaces."""
    modern = set(DEFAULT_COMMAND_REGISTRY.names())
    legacy = set(LEGACY_COMMANDS)
    print("usage: token-saver <command> [options]")
    print()
    print("Token Saver commands:")
    for name in sorted(modern | legacy):
        suffix = " (legacy-compatible)" if name in legacy and name not in modern else ""
        print(f"  {name}{suffix}")
    print()
    print("Run 'token-saver <command> --help' for flags.")
    print("See docs/CLI_REFERENCE.md for exit codes and JSON contracts.")


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested command while preserving legacy CLI behavior."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        _print_help()
        return 0
    return DEFAULT_COMMAND_REGISTRY.dispatch(args, legacy_main)


if __name__ == "__main__":
    raise SystemExit(main())

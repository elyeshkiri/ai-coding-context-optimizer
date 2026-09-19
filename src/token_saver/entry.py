"""Stable top-level command dispatcher.

Command registration lives in :mod:`token_saver.command_registry`; this module
owns only argv acquisition and fallback to the mature legacy CLI.
"""

from __future__ import annotations

import sys

from .cli import main as legacy_main
from .command_registry import DEFAULT_COMMAND_REGISTRY


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested command while preserving legacy CLI behavior."""
    args = list(sys.argv[1:] if argv is None else argv)
    return DEFAULT_COMMAND_REGISTRY.dispatch(args, legacy_main)


if __name__ == "__main__":
    raise SystemExit(main())

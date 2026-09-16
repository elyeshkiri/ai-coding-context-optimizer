"""Stable top-level dispatcher.

Keep the mature legacy CLI untouched while allowing high-value commands to be
implemented as isolated modules. This reduces regression risk in hook tooling.
"""

from __future__ import annotations

import sys

from .cli import main as legacy_main
from .pack_cli import main as pack_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "pack":
        return pack_main(args[1:])
    return legacy_main(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Stable top-level dispatcher.

Keep the mature legacy CLI untouched while allowing high-value commands to be
implemented as isolated modules. This reduces regression risk in hook tooling.
"""

from __future__ import annotations

import sys

from .cli import main as legacy_main
from .pack_cli import main as pack_main
from .commands import (
    agent_evaluate_main, evaluate_main, feedback_main, host_check_main, impact_main,
    pack_diff_main, review_main, serve_main,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "pack":
        return pack_main(args[1:])
    if args and args[0] == "impact":
        return impact_main(args[1:])
    if args and args[0] == "feedback":
        return feedback_main(args[1:])
    if args and args[0] == "evaluate":
        return evaluate_main(args[1:])
    if args and args[0] == "agent-evaluate":
        return agent_evaluate_main(args[1:])
    if args and args[0] == "host-check":
        return host_check_main(args[1:])
    if args and args[0] == "serve":
        return serve_main(args[1:])
    if args and args[0] == "pack-diff":
        return pack_diff_main(args[1:])
    if args and args[0] == "review":
        return review_main(args[1:])
    return legacy_main(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entry point for task-aware context packing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pack import build_context_pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="token-saver-pack",
        description="Build a task-aware source context pack under a hard token budget.",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("-q", "--query", default="", help="task/bug/feature description")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--context-lines", type=int, default=6)
    parser.add_argument("--no-gitignore", action="store_true")
    parser.add_argument("--no-changed-boost", action="store_true")
    parser.add_argument("--graph-hops", type=int, default=1,
                        help="dependency/call graph expansion depth (default: 1)")
    parser.add_argument("--duplicate-threshold", type=float, default=0.92,
                        help="identifier similarity at which a file is skipped")
    parser.add_argument("--session", help="remember the selected working set for related tasks")
    parser.add_argument("--embeddings", action="store_true",
                        help="rerank with an already-downloaded local sentence-transformer")
    parser.add_argument("--no-index-cache", action="store_true")
    parser.add_argument("--explain", action="store_true",
                        help="print the top relevance scores on stderr")
    parser.add_argument("-o", "--out", help="write pack to a file instead of stdout")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"not found: {root}", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1
    try:
        pack = build_context_pack(
            root,
            args.query,
            max_tokens=args.max_tokens,
            max_files=args.max_files,
            context_lines=args.context_lines,
            use_gitignore=not args.no_gitignore,
            changed_boost=not args.no_changed_boost,
            graph_hops=args.graph_hops,
            duplicate_threshold=args.duplicate_threshold,
            session=args.session,
            embeddings=args.embeddings,
            persist_index=not args.no_index_cache,
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.out:
        Path(args.out).write_text(pack.text, encoding="utf-8")
        print(
            f"wrote {args.out} ({pack.estimated_tokens} estimated tokens, "
            f"{len(pack.selected_files)}/{pack.scanned_files} files)",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(pack.text)

    if args.explain:
        print("\nTOKEN-SAVER RELEVANCE", file=sys.stderr)
        for item in pack.ranked[: min(20, len(pack.ranked))]:
            marker = "*" if item.rel in pack.selected_files else " "
            print(
                f"{marker} {item.score:7.2f}  {item.rel:50}  {', '.join(item.reasons)}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

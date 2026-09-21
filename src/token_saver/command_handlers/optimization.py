"""CLI handlers for recovery, optimization, provider proxy, and browser context."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

from ..browser_context import compress_browser_payload
from ..optimizer import (
    apply_optimization,
    evaluate_optimization,
    optimization_status,
    propose_optimizations,
)
from ..prefix_cache import prefix_status
from ..provider_proxy import ProviderProxyConfig, run_provider_proxy
from ..recovery import RecoveryStore
from ..runtime_config import settings_for


def recover_main(argv: list[str]) -> int:
    """Recover exact bytes stored before a lossy transformation."""
    parser = argparse.ArgumentParser(prog="token-saver recover")
    parser.add_argument("handle")
    parser.add_argument("--path", default=".")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        record = RecoveryStore(Path(args.path)).get(args.handle)
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(record.payload)
    if args.json:
        try:
            payload = record.payload.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            payload = base64.b64encode(record.payload).decode("ascii")
            encoding = "base64"
        print(json.dumps({
            "handle": record.handle,
            "content_type": record.content_type,
            "encoding": encoding,
            "payload": payload if not args.output else None,
            "output": str(Path(args.output).resolve()) if args.output else None,
            "size_bytes": record.size_bytes,
            "metadata": record.metadata,
            "access_count": record.access_count,
        }, indent=2))
        return 0
    if args.output:
        print(str(Path(args.output).resolve()))
        return 0
    try:
        sys.stdout.write(record.payload.decode("utf-8"))
    except UnicodeDecodeError:
        sys.stdout.buffer.write(record.payload)
    return 0


def recovery_status_main(argv: list[str]) -> int:
    """Report recovery-store capacity without exposing recovered bytes."""
    parser = argparse.ArgumentParser(prog="token-saver recovery-status")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = RecoveryStore(Path(args.path)).stats()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("TOKEN SAVER RECOVERY")
        print(f"records:   {report['records']}")
        print(f"used:      {report['used_bytes']} bytes")
        print(f"remaining: {report['remaining_bytes']} bytes")
        print(f"path:      {report['path']}")
    return 0


def prefix_status_main(argv: list[str]) -> int:
    """Report content-free stable-prefix reuse counters."""
    parser = argparse.ArgumentParser(prog="token-saver prefix-status")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = prefix_status(Path(args.path))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("TOKEN SAVER PREFIX CACHE")
    if not report["providers"]:
        print("no provider-prefix observations")
        return 0
    for provider, item in report["providers"].items():
        rate = item["reuse_rate"]
        rate_text = "n/a" if rate is None else f"{rate:.1%}"
        print(
            f"{provider}: reuse={rate_text} "
            f"hits={item['hits']} misses={item['misses']} "
            f"stable={item['stable_tokens']} tokens"
        )
    return 0


def browser_context_main(argv: list[str]) -> int:
    """Compress captured HTML or AX-like text without fetching a URL."""
    parser = argparse.ArgumentParser(prog="token-saver browser-context")
    parser.add_argument("input", help="captured HTML/text file, or - for stdin")
    parser.add_argument("--path", default=".", help="project root for recovery")
    parser.add_argument("--query", default="")
    parser.add_argument("--max-lines", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = (
            sys.stdin.read()
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8")
        )
        result = compress_browser_payload(
            text,
            query=args.query,
            max_lines=args.max_lines,
            recovery=RecoveryStore(Path(args.path)),
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.text)
    return 0


def provider_proxy_main(argv: list[str]) -> int:
    """Run the opt-in local provider optimization reverse proxy."""
    parser = argparse.ArgumentParser(prog="token-saver provider-proxy")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--upstream", required=True)
    parser.add_argument(
        "--provider",
        default="generic",
        choices=["generic", "anthropic", "openai", "gemini"],
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--tool-result-min-tokens", type=int, default=800)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--no-schema-compression", action="store_true")
    parser.add_argument("--no-tool-result-compression", action="store_true")
    parser.add_argument("--allow-non-loopback", action="store_true")
    parser.add_argument("--no-prefix-tracking", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    settings = settings_for(root)
    try:
        config = ProviderProxyConfig(
            root=root,
            upstream=args.upstream,
            provider=args.provider,
            bind=args.bind,
            port=args.port,
            compress_schemas=not args.no_schema_compression,
            compress_tool_results=not args.no_tool_result_compression,
            tool_result_min_tokens=args.tool_result_min_tokens,
            timeout_seconds=args.timeout_seconds,
            allow_non_loopback=args.allow_non_loopback,
            prefix_tracking=(
                settings.prefix_tracking and not args.no_prefix_tracking
            ),
        ).validate()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"token-saver provider proxy: http://{config.bind}:{config.port} "
        f"-> {config.upstream}",
        file=sys.stderr,
    )
    try:
        run_provider_proxy(config)
    except KeyboardInterrupt:
        return 0
    return 0


def optimize_main(argv: list[str]) -> int:
    """Plan, apply, or evaluate reversible measured optimization changes."""
    parser = argparse.ArgumentParser(prog="token-saver optimize")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--apply", metavar="PROPOSAL_ID")
    parser.add_argument("--evaluate", metavar="RUN_ID")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--min-turns", type=int, default=5)
    parser.add_argument("--min-improvement", type=float, default=0.0)
    parser.add_argument("--no-auto-revert", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.path)
    try:
        if args.evaluate:
            result = evaluate_optimization(
                root,
                args.evaluate,
                min_turns=args.min_turns,
                min_improvement=args.min_improvement,
                revert_on_no_gain=not args.no_auto_revert,
            )
        elif args.apply:
            result = apply_optimization(root, args.apply, days=args.days)
        elif args.status:
            result = {"runs": optimization_status(root)}
        else:
            result = propose_optimizations(root, days=args.days)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    if args.evaluate:
        print(f"OPTIMIZATION {result['id']}: {result.get('decision')}")
        print(
            "baseline: "
            f"{result.get('baseline_mean_tokens_per_turn')} tokens/turn "
            f"({result.get('baseline_turns')} turns)"
        )
        print(
            "treatment: "
            f"{result.get('treatment_mean_tokens_per_turn')} tokens/turn "
            f"({result.get('treatment_turns')} turns)"
        )
        print(f"reverted: {result.get('reverted', False)}")
        return 0
    if args.apply:
        print(f"APPLIED {result['proposal']['id']} as {result['id']}")
        print(f"backup: {result['recovery_handle']}")
        print(
            "Run normal work, then evaluate with: "
            f"token-saver optimize {args.path} --evaluate {result['id']}"
        )
        return 0
    if args.status:
        runs = result["runs"]
        print(f"OPTIMIZATION RUNS: {len(runs)}")
        for item in runs:
            print(
                f"{item.get('id')} {item.get('status')} "
                f"{item.get('proposal', {}).get('id')}"
            )
        return 0

    print("TOKEN SAVER OPTIMIZATION PLAN")
    if not result["proposals"]:
        print("no safe Token Saver-owned config proposals from current evidence")
    for item in result["proposals"]:
        print(f"[{item['risk']}] {item['id']}: {item['title']}")
        print(f"  {item['rationale']}")
    print("proposals are hypotheses until post-change measured evaluation")
    return 0

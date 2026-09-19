"""Host integration CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..host_validate import validate_host
from ..integration_setup import (
    HOSTS,
    doctor_report,
    setup_integrations,
    uninstall_integrations,
)
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


def _hosts_argument(parser: argparse.ArgumentParser) -> None:
    """Add repeatable host selection to an integration command."""
    parser.add_argument(
        "--host",
        action="append",
        choices=[*HOSTS, "all"],
        help="host to configure; repeat for multiple hosts (default: auto-detect)",
    )


def setup_main(argv: list[str]) -> int:
    """Auto-detect and configure Token Saver integrations."""
    parser = argparse.ArgumentParser(prog="token-saver setup")
    parser.add_argument("path", nargs="?", default=".")
    _hosts_argument(parser)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = setup_integrations(
            Path(args.path),
            tuple(args.host) if args.host else None,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print("TOKEN SAVER SETUP")
    print(f"project: {result['root']}")
    print(f"config:  {result['config']}")
    if result["configured_hosts"]:
        print("configured: " + ", ".join(result["configured_hosts"]))
    else:
        print("configured: none (no supported host detected)")
        print("hint: rerun with --host claude|cursor|codex|all")
    print("next: token-saver doctor " + result["root"])
    return 0


def doctor_main(argv: list[str]) -> int:
    """Run one consolidated installation and integration health check."""
    parser = argparse.ArgumentParser(prog="token-saver doctor")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = doctor_report(Path(args.path), index=not args.no_index)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"TOKEN SAVER DOCTOR {report['version']}")
        print("status: " + ("READY" if report["ready"] else "NEEDS ATTENTION"))
        print(f"cli:    {report['token_saver_executable'] or 'not found in PATH'}")
        print(f"config: {report['config_path'] or 'not found'}")
        if report["config_error"]:
            print(f"config error: {report['config_error']}")
        for host in report["hosts"]:
            detected = "detected" if host["detected"] else "not detected"
            configured = "configured" if host["configured"] else "not configured"
            print(f"{host['name']:<7} {detected}, {configured}")
        if report["index"]:
            print(
                "index:  "
                f"{report['index']['files']} files, "
                f"version {report['index']['index_version']}"
            )
        elif report["index_error"]:
            print(f"index error: {report['index_error']}")
        print(f"claude usage evidence: {report['claude_transcripts']} transcript(s)")
        if not report["ready"]:
            print("repair: token-saver setup " + report["root"])
    return 1 if args.require_ready and not report["ready"] else 0


def uninstall_main(argv: list[str]) -> int:
    """Safely remove Token Saver-owned host integration entries."""
    parser = argparse.ArgumentParser(prog="token-saver uninstall")
    parser.add_argument("path", nargs="?", default=".")
    _hosts_argument(parser)
    parser.add_argument("--remove-config", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = uninstall_integrations(
            Path(args.path),
            tuple(args.host) if args.host else None,
            remove_config=args.remove_config,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("TOKEN SAVER UNINSTALL")
        print("removed: " + ", ".join(result["removed_hosts"]))
        if result["config_removed"]:
            print("project config removed")
    return 0


def completion_main(argv: list[str]) -> int:
    """Generate lightweight shell completion for top-level commands."""
    parser = argparse.ArgumentParser(prog="token-saver completion")
    parser.add_argument("shell", choices=["bash", "zsh", "fish"])
    args = parser.parse_args(argv)

    from ..command_registry import DEFAULT_COMMAND_REGISTRY

    names = " ".join(DEFAULT_COMMAND_REGISTRY.names())
    if args.shell == "bash":
        print(
            "_token_saver_complete() {\\n"
            '  local cur="${COMP_WORDS[COMP_CWORD]}"\\n'
            f'  COMPREPLY=( $(compgen -W "{names}" -- "$cur") )\\n'
            "}\\n"
            "complete -F _token_saver_complete token-saver"
        )
    elif args.shell == "zsh":
        print(f"#compdef token-saver\\n_arguments \'1:command:({names})\'")
    else:
        for name in DEFAULT_COMMAND_REGISTRY.names():
            print(f"complete -c token-saver -n \'__fish_use_subcommand\' -a \'{name}\'")
    return 0


def commands_main(argv: list[str]) -> int:
    """List discoverable top-level commands."""
    parser = argparse.ArgumentParser(prog="token-saver commands")
    parser.parse_args(argv)
    from ..command_registry import DEFAULT_COMMAND_REGISTRY

    print("TOKEN SAVER COMMANDS")
    for name in DEFAULT_COMMAND_REGISTRY.names():
        print(name)
    print("\\nUse: token-saver <command> --help")
    return 0

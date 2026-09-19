"""Extensible command registry for the top-level Token Saver CLI."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .commands import (
    agent_evaluate_main,
    browse_main,
    cost_report_main,
    evaluate_main,
    experiment_main,
    feedback_main,
    host_check_main,
    impact_main,
    output_benchmark_main,
    output_explain_main,
    output_policy_main,
    output_replay_main,
    output_save_main,
    pack_diff_main,
    review_main,
    serve_main,
)
from .pack_cli import main as pack_main

CommandHandler = Callable[[list[str]], int]


@dataclass(frozen=True)
class CommandSpec:
    """Bind one top-level command name to its handler."""

    name: str
    handler: CommandHandler


class CommandRegistry:
    """Dispatch top-level commands without embedding command knowledge in entry.py."""

    def __init__(self, specs: Iterable[CommandSpec]):
        """Build a registry and reject ambiguous duplicate command names."""
        handlers: dict[str, CommandHandler] = {}
        for spec in specs:
            if spec.name in handlers:
                raise ValueError(f"duplicate command registration: {spec.name}")
            handlers[spec.name] = spec.handler
        self._handlers = handlers

    def dispatch(self, args: list[str], fallback: CommandHandler) -> int:
        """Dispatch ``args`` to a registered handler or ``fallback``."""
        if not args:
            return fallback(args)
        handler = self._handlers.get(args[0])
        if handler is None:
            return fallback(args)
        return handler(args[1:])

    def names(self) -> tuple[str, ...]:
        """Return registered command names in deterministic order."""
        return tuple(sorted(self._handlers))


DEFAULT_COMMAND_REGISTRY = CommandRegistry(
    [
        CommandSpec("pack", pack_main),
        CommandSpec("impact", impact_main),
        CommandSpec("browse", browse_main),
        CommandSpec("feedback", feedback_main),
        CommandSpec("evaluate", evaluate_main),
        CommandSpec("agent-evaluate", agent_evaluate_main),
        CommandSpec("experiment", experiment_main),
        CommandSpec("cost-report", cost_report_main),
        CommandSpec("host-check", host_check_main),
        CommandSpec("output-policy", output_policy_main),
        CommandSpec("output-benchmark", output_benchmark_main),
        CommandSpec("output-explain", output_explain_main),
        CommandSpec("output-replay", output_replay_main),
        CommandSpec("output-save", output_save_main),
        CommandSpec("serve", serve_main),
        CommandSpec("pack-diff", pack_diff_main),
        CommandSpec("review", review_main),
    ]
)

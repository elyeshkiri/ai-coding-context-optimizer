"""Extensible command registry for the top-level Token Saver CLI."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .command_handlers.context import (
    browse_main,
    feedback_main,
    impact_main,
    knowledge_status_main,
    ranking_explain_main,
    recall_main,
    remember_main,
)
from .command_handlers.efficiency import continuity_main, dashboard_main
from .command_handlers.evaluation import (
    agent_evaluate_main,
    blind_grade_main,
    evaluate_main,
    ranking_calibrate_main,
    ranking_diff_main,
    ranking_snapshot_main,
)
from .command_handlers.experiment import (
    cost_report_main,
    evidence_run_main,
    experiment_main,
    session_holdout_evaluate_main,
    session_holdout_main,
)
from .command_handlers.host import (
    commands_main,
    completion_main,
    doctor_main,
    host_check_main,
    serve_main,
    setup_main,
    uninstall_main,
)
from .command_handlers.output import (
    output_benchmark_main,
    output_calibrate_main,
    output_effectiveness_main,
    output_explain_main,
    output_policy_main,
    output_replay_main,
    output_save_main,
    output_telemetry_main,
)
from .command_handlers.patch import pack_diff_main, review_main
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
        CommandSpec("ranking-explain", ranking_explain_main),
        CommandSpec("remember", remember_main),
        CommandSpec("recall", recall_main),
        CommandSpec("knowledge-status", knowledge_status_main),
        CommandSpec("evaluate", evaluate_main),
        CommandSpec("agent-evaluate", agent_evaluate_main),
        CommandSpec("blind-grade", blind_grade_main),
        CommandSpec("ranking-snapshot", ranking_snapshot_main),
        CommandSpec("ranking-diff", ranking_diff_main),
        CommandSpec("ranking-calibrate", ranking_calibrate_main),
        CommandSpec("experiment", experiment_main),
        CommandSpec("evidence-run", evidence_run_main),
        CommandSpec("session-holdout", session_holdout_main),
        CommandSpec("session-holdout-evaluate", session_holdout_evaluate_main),
        CommandSpec("cost-report", cost_report_main),
        CommandSpec("dashboard", dashboard_main),
        CommandSpec("continuity", continuity_main),
        CommandSpec("setup", setup_main),
        CommandSpec("doctor", doctor_main),
        CommandSpec("uninstall", uninstall_main),
        CommandSpec("completion", completion_main),
        CommandSpec("commands", commands_main),
        CommandSpec("host-check", host_check_main),
        CommandSpec("output-policy", output_policy_main),
        CommandSpec("output-benchmark", output_benchmark_main),
        CommandSpec("output-calibrate", output_calibrate_main),
        CommandSpec("output-effectiveness", output_effectiveness_main),
        CommandSpec("output-explain", output_explain_main),
        CommandSpec("output-replay", output_replay_main),
        CommandSpec("output-save", output_save_main),
        CommandSpec("output-telemetry", output_telemetry_main),
        CommandSpec("serve", serve_main),
        CommandSpec("pack-diff", pack_diff_main),
        CommandSpec("review", review_main),
    ]
)

"""Compatibility facade for vertical CLI command handlers.

New code should import handlers from :mod:`token_saver.command_handlers`
submodules. This module preserves the pre-refactor import surface only.
"""

from .command_handlers.context import (
    browse_main,
    feedback_main,
    impact_main,
    knowledge_status_main,
    ranking_explain_main,
    recall_main,
    remember_main,
)
from .command_handlers.efficiency import cache_economics_main
from .command_handlers.evaluation import (
    agent_evaluate_main,
    evaluate_main,
    ranking_calibrate_main,
    ranking_diff_main,
    ranking_snapshot_main,
)
from .command_handlers.experiment import cost_report_main, experiment_main
from .command_handlers.host import (
    commands_main,
    fastpath_status_main,
    completion_main,
    doctor_main,
    host_check_main,
    serve_main,
    setup_main,
    uninstall_main,
)
from .command_handlers.ingress import ingress_read_main, ingress_show_main
from .command_handlers.output import (
    output_benchmark_main,
    output_explain_main,
    output_policy_main,
    output_replay_main,
    output_save_main,
)
from .command_handlers.patch import pack_diff_main, review_main

__all__ = [
    "agent_evaluate_main",
    "browse_main",
    "cache_economics_main",
    "commands_main",
    "completion_main",
    "cost_report_main",
    "doctor_main",
    "evaluate_main",
    "experiment_main",
    "feedback_main",
    "fastpath_status_main",
    "host_check_main",
    "impact_main",
    "knowledge_status_main",
    "ingress_read_main",
    "ingress_show_main",
    "output_benchmark_main",
    "output_explain_main",
    "output_policy_main",
    "output_replay_main",
    "output_save_main",
    "pack_diff_main",
    "ranking_calibrate_main",
    "ranking_diff_main",
    "ranking_explain_main",
    "recall_main",
    "remember_main",
    "ranking_snapshot_main",
    "review_main",
    "serve_main",
    "setup_main",
    "uninstall_main",
]

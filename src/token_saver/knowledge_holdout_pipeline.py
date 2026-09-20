"""Run and evaluate the frozen knowledge-efficiency holdout end to end."""

from __future__ import annotations

from pathlib import Path

from .blind_grader import blind_grade_manifest, validate_grader_config
from .experiment import run_experiment, validate_suite
from .knowledge_holdout import (
    evaluate_knowledge_holdout,
    validate_knowledge_holdout_definition,
)
from .session_holdout_pipeline import (
    _atomic_write,
    _pricing_path,
    load_session_pricing,
)


def run_knowledge_holdout(
    suite_path: Path,
    output_path: Path,
    *,
    rates_path: Path | None = None,
    report_path: Path | None = None,
    allow_development: bool = False,
    allow_user_hook: bool = False,
    only_tasks: set[str] | None = None,
    force_grades: bool = False,
    dry_run: bool = False,
    require_publishable: bool = False,
) -> dict:
    """Run/resume experiment, blind grading, and knowledge-effect evaluation."""
    suite_path = suite_path.resolve()
    output_path = output_path.resolve()
    suite = validate_suite(
        suite_path,
        require_frozen=not allow_development,
        require_broad=not allow_development,
    )
    grader = validate_grader_config(suite)
    definition = validate_knowledge_holdout_definition(
        suite,
        require_frozen=not allow_development,
    )
    runner = suite.get("runner")
    protocol_version = (
        runner.get("knowledge_holdout_protocol_version")
        if isinstance(runner, dict)
        else None
    )
    if protocol_version != 1:
        raise ValueError("runner.knowledge_holdout_protocol_version must be 1")

    pricing_file = _pricing_path(suite_path, suite, rates_path)
    model = str(suite["runner"]["model"])
    pricing = load_session_pricing(pricing_file, model)

    experiment = run_experiment(
        suite_path,
        output_path,
        dry_run=dry_run,
        allow_development=allow_development,
        allow_user_hook=allow_user_hook,
        only_tasks=only_tasks,
    )
    if dry_run:
        return {
            "schema": 1,
            "stage": "dry-run",
            "comparison": definition["comparison"],
            "experiment": experiment,
            "grader": grader,
            "pricing_file": str(pricing_file),
            "pricing_model": model,
        }

    blind_grade_manifest(
        output_path,
        output_path=output_path,
        force=force_grades,
    )
    report = evaluate_knowledge_holdout(output_path, pricing=pricing)
    destination = (
        report_path.resolve()
        if report_path is not None
        else output_path.with_name(
            output_path.stem + ".knowledge-effectiveness.json"
        )
    )
    _atomic_write(destination, report)

    summary = {
        "schema": 1,
        "stage": "complete",
        "suite": str(suite_path),
        "runs": str(output_path),
        "report": str(destination),
        "tasks": report["tasks"],
        "paired_trials": report["paired_trials"],
        "reductions": report["reductions"],
        "feature_activation": report["feature_activation"],
        "publication_gate": report["publication_gate"],
        "claim_allowed": report["claim_allowed"],
    }
    if require_publishable and not report["publication_gate"]["passed"]:
        blockers = ", ".join(report["publication_gate"]["blockers"])
        raise ValueError("knowledge holdout is not publishable: " + blockers)
    return summary

"""Run and evaluate the frozen session-efficiency holdout end to end."""

from __future__ import annotations

import json
from pathlib import Path

from .blind_grader import blind_grade_manifest, validate_grader_config
from .experiment import run_experiment, validate_suite
from .output_effectiveness import EffectivenessPricing
from .session_holdout import evaluate_session_holdout


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomically write one session-holdout report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_session_pricing(path: Path, model: str) -> EffectivenessPricing:
    """Load cache-TTL-aware rates for the frozen holdout model."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pricing file must be a JSON object")
    rates = payload.get(model)
    if not isinstance(rates, dict):
        raise ValueError(f"pricing file has no rates for model {model!r}")

    def rate(name: str) -> float | None:
        """Return one optional numeric rate."""
        value = rates.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"pricing {model}.{name} must be numeric")
        return float(value)

    pricing = EffectivenessPricing(
        fresh_input_per_million=rate("input"),
        cache_creation_5m_per_million=rate("cache_write_5m"),
        cache_creation_1h_per_million=rate("cache_write_1h"),
        cache_creation_unknown_per_million=rate("cache_write_unknown"),
        cache_read_per_million=rate("cache_read"),
        output_per_million=rate("output"),
    )
    pricing.validate()
    return pricing


def _pricing_path(
    suite_path: Path,
    suite: dict,
    explicit: Path | None,
) -> Path:
    """Resolve explicit or suite-declared pricing evidence."""
    if explicit is not None:
        return explicit.resolve()
    evidence = suite.get("evidence")
    declared = evidence.get("pricing_file") if isinstance(evidence, dict) else None
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("session holdout requires --rates or evidence.pricing_file")
    path = Path(declared)
    return path if path.is_absolute() else (suite_path.parent / path).resolve()


def run_session_holdout(
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
    """Run/resume experiment, blind grading, and session-effect evaluation."""
    suite_path = suite_path.resolve()
    output_path = output_path.resolve()
    suite = validate_suite(
        suite_path,
        require_frozen=not allow_development,
        require_broad=not allow_development,
    )
    grader = validate_grader_config(suite)
    runner = suite.get("runner")
    protocol_version = (
        runner.get("session_holdout_protocol_version")
        if isinstance(runner, dict)
        else None
    )
    if protocol_version != 1:
        raise ValueError("runner.session_holdout_protocol_version must be 1")

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
            "comparison": {
                "baseline": "v1.6-session-baseline",
                "treatment": "v1.7-session-efficiency",
            },
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
    report = evaluate_session_holdout(output_path, pricing=pricing)
    destination = (
        report_path.resolve()
        if report_path is not None
        else output_path.with_name(output_path.stem + ".session-effectiveness.json")
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
        raise ValueError("session holdout is not publishable: " + blockers)
    return summary

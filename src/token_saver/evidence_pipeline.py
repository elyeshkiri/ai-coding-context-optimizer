"""Resumable end-to-end output evidence pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from .blind_grader import blind_grade_manifest, validate_grader_config
from .experiment import run_experiment, validate_suite
from .output_budget import calibrate_output_budgets
from .output_effectiveness import EffectivenessPricing, evaluate_output_effectiveness


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomically write one pipeline artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _pricing_from_rates(path: Path, model: str) -> EffectivenessPricing:
    """Load one model's cache-TTL-aware pricing from a rate table."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("pricing file must be a JSON object")
    rates = payload.get(model)
    if not isinstance(rates, dict):
        raise ValueError(f"pricing file has no rates for model {model!r}")

    def optional(name: str) -> float | None:
        value = rates.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"pricing {model}.{name} must be numeric")
        return float(value)

    pricing = EffectivenessPricing(
        fresh_input_per_million=optional("input"),
        cache_creation_5m_per_million=optional("cache_write_5m"),
        cache_creation_1h_per_million=optional("cache_write_1h"),
        cache_creation_unknown_per_million=optional("cache_write_unknown"),
        cache_read_per_million=optional("cache_read"),
        output_per_million=optional("output"),
    )
    pricing.validate()
    return pricing


def _resolve_rates(
    suite_path: Path,
    suite: dict,
    rates_path: Path | None,
) -> Path:
    """Resolve explicit or suite-declared pricing evidence."""
    if rates_path is not None:
        return rates_path.resolve()
    evidence = suite.get("evidence")
    declared = evidence.get("pricing_file") if isinstance(evidence, dict) else None
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError(
            "evidence pipeline requires --rates or evidence.pricing_file"
        )
    path = Path(declared)
    if not path.is_absolute():
        path = (suite_path.parent / path).resolve()
    return path


def run_evidence_pipeline(
    suite_path: Path,
    output_path: Path,
    *,
    rates_path: Path | None = None,
    report_path: Path | None = None,
    calibration_path: Path | None = None,
    allow_development: bool = False,
    allow_user_hook: bool = False,
    only_tasks: set[str] | None = None,
    force_grades: bool = False,
    dry_run: bool = False,
    require_publishable: bool = False,
) -> dict:
    """Run/resume experiment, blind grading, effectiveness, and calibration."""
    suite_path = suite_path.resolve()
    output_path = output_path.resolve()
    suite = validate_suite(
        suite_path,
        require_frozen=not allow_development,
        require_broad=not allow_development,
    )
    grader = validate_grader_config(suite)
    pricing_file = _resolve_rates(suite_path, suite, rates_path)
    model = str(suite["runner"]["model"])
    pricing = _pricing_from_rates(pricing_file, model)

    if dry_run:
        experiment_plan = run_experiment(
            suite_path,
            output_path,
            dry_run=True,
            allow_development=allow_development,
            allow_user_hook=allow_user_hook,
            only_tasks=only_tasks,
        )
        grader_probe = {
            **grader,
            "pricing_file": str(pricing_file),
            "pricing_model": model,
        }
        return {
            "stage": "dry-run",
            "experiment": experiment_plan,
            "grader": grader_probe,
        }

    run_experiment(
        suite_path,
        output_path,
        allow_development=allow_development,
        allow_user_hook=allow_user_hook,
        only_tasks=only_tasks,
    )
    graded = blind_grade_manifest(
        output_path,
        output_path=output_path,
        force=force_grades,
    )
    effectiveness = evaluate_output_effectiveness(
        output_path,
        pricing=pricing,
    )

    final_report = (
        report_path.resolve()
        if report_path is not None
        else output_path.with_name(output_path.stem + ".effectiveness.json")
    )
    _atomic_write(final_report, effectiveness)

    calibration = calibrate_output_budgets(output_path)
    final_calibration = (
        calibration_path.resolve()
        if calibration_path is not None
        else output_path.with_name(output_path.stem + ".output-calibration.json")
    )
    _atomic_write(final_calibration, calibration)

    summary = {
        "schema": 1,
        "stage": "complete",
        "suite": str(suite_path),
        "runs": str(output_path),
        "effectiveness": str(final_report),
        "calibration": str(final_calibration),
        "graded_pairs": graded["quality_evaluation"]["completed_pairs"],
        "publication_gate": effectiveness["publication_gate"],
        "claim_allowed": effectiveness["claim_allowed"],
    }
    if require_publishable and not effectiveness["publication_gate"]["passed"]:
        blockers = ", ".join(effectiveness["publication_gate"]["blockers"])
        raise ValueError("evidence pipeline is not publishable: " + blockers)
    return summary

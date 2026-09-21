"""Deterministic capability-, evidence-, and price-aware model routing.

Static routing is deliberately conservative. A cheaper model may cross the
static capability boundary only through an exact quality-gated calibration
bucket produced from frozen paired experiments with independent success
verification, blind response grading, and transcript-confirmed model identity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path

from .agent_eval import QUALITY_WEIGHTS
from .efficiency.store import append_event
from .estimate import estimate_tokens
from .generation_policy import classify_output_task
from .output_budget import adaptive_output_budget
from .output_saver import OUTPUT_TASKS
from .paired_conditions import normalize_condition
from .policy import looks_like_new_task
from .pricing import FIELDS, builtin_rates, builtin_registry
from .state import load as load_state
from .state import update as update_state

ROUTING_MODES = ("observe", "advisory")
DEFAULT_ALLOWED_MODELS = (
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-5",
)
ROUTING_CALIBRATION_SCHEMA = 1
DEFAULT_ROUTING_CALIBRATION_FILE = ".token-saver.routing-calibration.json"
MIN_CALIBRATION_PAIRS = 10
MIN_CALIBRATION_TASKS = 5
MIN_BASELINE_SUCCESS_RATE = 0.80
MAX_QUALITY_DROP = 0.10
_REQUIRED_CALIBRATION_PROTOCOL = (
    "task_definitions_frozen",
    "condition_order_randomized",
    "independent_verification",
    "history_isolated",
    "hidden_tests_after_agent",
)

_CAPABILITY = {"economy": 1, "balanced": 2, "deep": 3}
_COMPLEXITY = {"simple": 0, "standard": 1, "complex": 2, "extended": 3}

_MODEL_PROFILES = {
    "claude-haiku-4-5": {
        "capability": "economy",
        "tasks": {"general", "explanation", "planning", "coding"},
        "max_complexity": "standard",
    },
    "claude-sonnet-5": {
        "capability": "balanced",
        "tasks": {
            "general",
            "explanation",
            "planning",
            "coding",
            "debugging",
            "review",
        },
        "max_complexity": "extended",
    },
    "claude-opus-5": {
        "capability": "deep",
        "tasks": {
            "general",
            "explanation",
            "planning",
            "coding",
            "debugging",
            "review",
        },
        "max_complexity": "extended",
    },
}

_HIGH_RISK_RE = re.compile(
    r"\b("
    r"security|secure|vulnerability|auth(?:entication|orization)?|permission|"
    r"cryptograph|encrypt|payment|billing|production|incident|outage|"
    r"data[ -]?loss|destructive|database[ -]?migration|schema[ -]?migration|"
    r"distributed|concurren|race[ -]?condition|deadlock|memory[ -]?corruption|"
    r"release|deploy(?:ment)?|infrastructure|terraform|kubernetes"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelRouteDecision:
    """Describe one deterministic model-routing decision."""

    task: str
    complexity_tier: str
    complexity_score: int
    risk_level: str
    risk_signals: tuple[str, ...]
    minimum_capability: str
    selected_model: str | None
    current_model: str | None
    action: str
    allowed_models: tuple[str, ...]
    eligible_models: tuple[str, ...]
    calibrated_models: tuple[str, ...]
    calibration_applied: bool
    calibration_source: str | None
    estimated_input_tokens: int
    input_token_basis: str
    estimated_output_tokens: int
    projected_cost_usd: dict[str, float]
    projected_current_cost_usd: float | None
    projected_savings_fraction: float | None
    pricing_basis: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        """Return a stable machine-readable decision."""
        return asdict(self)


def _risk(prompt: str) -> tuple[str, tuple[str, ...]]:
    """Return a bounded risk level from explicit prompt vocabulary."""
    matches = sorted(
        {match.group(0).lower() for match in _HIGH_RISK_RE.finditer(prompt)}
    )
    if not matches:
        return "normal", ()
    return "high", tuple(matches[:8])


def _minimum_capability(
    task: str,
    complexity: str,
    *,
    risk_level: str,
    conservative: bool,
) -> tuple[str, tuple[str, ...]]:
    """Map visible task, tier, and risk into a minimum capability level."""
    reasons: list[str] = []
    required = 1

    if task in {"debugging", "review"}:
        required = max(required, 2)
        reasons.append(f"{task}_requires_balanced")

    if task in {"coding", "planning", "debugging", "review"}:
        if complexity == "extended":
            required = max(required, 3)
            reasons.append("extended_change_requires_deep")
        elif complexity == "complex":
            required = max(required, 2)
            reasons.append("complex_change_requires_balanced")
    elif complexity in {"complex", "extended"}:
        required = max(required, 2)
        reasons.append("complex_reasoning_requires_balanced")

    if conservative and risk_level == "high":
        if complexity in {"complex", "extended"}:
            required = max(required, 3)
            reasons.append("high_risk_complex_requires_deep")
        else:
            required = max(required, 2)
            reasons.append("high_risk_requires_balanced")

    name = next(
        capability
        for capability, rank in _CAPABILITY.items()
        if rank == required
    )
    return name, tuple(reasons)


def _route_features(
    prompt: str,
    *,
    task_override: str | None = None,
    conservative: bool = True,
):
    """Resolve the shared task/complexity/risk policy inputs."""
    if task_override is not None:
        task = task_override.strip().lower()
        if task not in OUTPUT_TASKS:
            raise ValueError(f"unknown routing task override: {task_override}")
    else:
        task = classify_output_task(prompt) or "general"
    budget = adaptive_output_budget(prompt, task=task, mode="normal")
    risk_level, risk_signals = _risk(prompt)
    minimum, requirement_reasons = _minimum_capability(
        task,
        budget.complexity_tier,
        risk_level=risk_level,
        conservative=conservative,
    )
    return task, budget, risk_level, risk_signals, minimum, requirement_reasons


def _eligible(
    model: str,
    *,
    task: str,
    complexity: str,
    minimum_capability: str,
) -> bool:
    """Return whether one explicit static profile satisfies routing requirements."""
    profile = _MODEL_PROFILES.get(model)
    if profile is None:
        return False
    if task not in profile["tasks"]:
        return False
    if _CAPABILITY[profile["capability"]] < _CAPABILITY[minimum_capability]:
        return False
    return (
        _COMPLEXITY[complexity]
        <= _COMPLEXITY[str(profile["max_complexity"])]
    )


def _one_turn_cost(
    model: str,
    rates: dict,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Project one fresh-input turn from explicit registry rates only."""
    rate = rates[model]
    return (
        input_tokens * rate["input"] + output_tokens * rate["output"]
    ) / 1_000_000


def _canonical_model(model: object) -> str | None:
    """Resolve a canonical routing model from the verified builtin registry."""
    if not isinstance(model, str) or not model.strip():
        return None
    value = model.strip()
    if value in _MODEL_PROFILES:
        return value
    registry = builtin_registry()
    for canonical, entry in registry["models"].items():
        if canonical not in _MODEL_PROFILES:
            continue
        if value == canonical or value in entry["aliases"]:
            return canonical
    return None


def _weighted_quality(quality: object) -> float:
    """Validate one blind quality object and return its weighted score."""
    if not isinstance(quality, dict):
        raise ValueError("routing calibration requires quality on every run")
    total = 0.0
    for name, weight in QUALITY_WEIGHTS.items():
        value = quality.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"quality.{name} must be numeric")
        score = float(value)
        if score < 1 or score > 5:
            raise ValueError(f"quality.{name} must be between 1 and 5")
        total += score * weight
    return total


def _verified_run_model(run: dict) -> str:
    """Return a declared model only when transcript evidence confirms it."""
    declared = _canonical_model(run.get("model"))
    if declared is None:
        raise ValueError("routing calibration run has unknown declared model")
    actual = run.get("actual_models")
    if not isinstance(actual, list) or len(actual) != 1:
        raise ValueError(
            "routing calibration requires exactly one transcript-confirmed actual model"
        )
    observed = _canonical_model(actual[0])
    if observed != declared:
        raise ValueError(
            "routing calibration declared model does not match transcript actual model"
        )
    return declared


def _policy_baseline_model(
    *,
    task: str,
    complexity: str,
    minimum_capability: str,
    rates: dict,
    input_tokens: int,
    output_tokens: int,
) -> str | None:
    """Return the cheapest model admitted by the uncalibrated static policy."""
    eligible = [
        model
        for model in DEFAULT_ALLOWED_MODELS
        if _eligible(
            model,
            task=task,
            complexity=complexity,
            minimum_capability=minimum_capability,
        )
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda model: (
            _one_turn_cost(
                model,
                rates,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            DEFAULT_ALLOWED_MODELS.index(model),
        ),
    )


def _recommendation_is_runtime_safe(item: object) -> bool:
    """Return whether a calibration recommendation still meets hard runtime floors."""
    if not isinstance(item, dict):
        return False
    baseline = _canonical_model(item.get("baseline_model"))
    candidate = _canonical_model(item.get("candidate_model"))
    if baseline is None or candidate is None:
        return False
    if _CAPABILITY[_MODEL_PROFILES[candidate]["capability"]] >= _CAPABILITY[
        _MODEL_PROFILES[baseline]["capability"]
    ]:
        return False
    integers = {
        "pairs": MIN_CALIBRATION_PAIRS,
        "tasks": MIN_CALIBRATION_TASKS,
        "regressions": 0,
    }
    for key, floor in integers.items():
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if key == "regressions":
            if value != 0:
                return False
        elif value < floor:
            return False
    baseline_success = item.get("baseline_success_rate")
    candidate_success = item.get("candidate_success_rate")
    if (
        isinstance(baseline_success, bool)
        or not isinstance(baseline_success, (int, float))
        or float(baseline_success) < MIN_BASELINE_SUCCESS_RATE
        or isinstance(candidate_success, bool)
        or not isinstance(candidate_success, (int, float))
        or float(candidate_success) < float(baseline_success)
    ):
        return False
    for key in (
        "mean_weighted_quality_delta",
        "mean_correctness_delta",
        "mean_safety_delta",
    ):
        value = item.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or float(value) < -MAX_QUALITY_DROP
        ):
            return False
    return all(
        item.get(key) is True
        for key in (
            "success_preserved",
            "quality_preserved",
            "actual_models_verified",
            "blinded_quality",
            "independent_verification",
            "baseline_matches_static_policy",
            "candidate_strictly_cheaper",
        )
    )


def load_routing_calibration(path: Path | None) -> dict:
    """Load a quality-gated routing artifact, failing closed on weak recommendations."""
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != ROUTING_CALIBRATION_SCHEMA:
        raise ValueError(
            f"routing calibration schema must be {ROUTING_CALIBRATION_SCHEMA}"
        )
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("routing calibration recommendations must be a list")
    if any(not _recommendation_is_runtime_safe(item) for item in recommendations):
        raise ValueError("routing calibration contains a recommendation below safety floors")
    return payload


def _calibrated_candidates(
    calibration: dict | None,
    *,
    task: str,
    complexity: str,
    risk_level: str,
    baseline_model: str | None,
) -> tuple[str, ...]:
    """Return exact-bucket candidates admitted by quality-gated evidence."""
    if not calibration or baseline_model is None:
        return ()
    recommendations = calibration.get("recommendations")
    if not isinstance(recommendations, list):
        return ()
    output: list[str] = []
    for item in recommendations:
        if not _recommendation_is_runtime_safe(item):
            continue
        if (
            item.get("task") == task
            and item.get("complexity_tier") == complexity
            and item.get("risk_level") == risk_level
            and _canonical_model(item.get("baseline_model")) == baseline_model
        ):
            candidate = _canonical_model(item.get("candidate_model"))
            if candidate and candidate not in output:
                output.append(candidate)
    return tuple(output)


def calibrate_model_routing(path: Path) -> dict:
    """Build exact routing exceptions from frozen, blind, independently verified pairs."""
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing calibration manifest must be a JSON object")

    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("routing calibration requires frozen experiment protocol metadata")
    missing_protocol = [
        name for name in _REQUIRED_CALIBRATION_PROTOCOL if protocol.get(name) is not True
    ]
    if missing_protocol:
        raise ValueError(
            "routing calibration requires protocol gates: "
            + ", ".join(missing_protocol)
        )

    runner = payload.get("runner")
    if not isinstance(runner, dict):
        raise ValueError("routing calibration requires runner metadata")
    profiles = runner.get("condition_profiles")
    if (
        not isinstance(profiles, dict)
        or set(profiles) != {"baseline", "enabled"}
        or not all(isinstance(profiles[name], dict) for name in profiles)
    ):
        raise ValueError(
            "routing calibration requires explicit baseline/enabled condition profiles"
        )
    baseline_profile = profiles["baseline"]
    candidate_profile = profiles["enabled"]
    for key in ("install_token_saver", "env"):
        if baseline_profile.get(key) != candidate_profile.get(key):
            raise ValueError(
                "routing calibration arms may differ only by model/label; "
                f"condition profile {key} differs"
            )
    baseline_profile_model = _canonical_model(baseline_profile.get("model"))
    candidate_profile_model = _canonical_model(candidate_profile.get("model"))
    if baseline_profile_model is None or candidate_profile_model is None:
        raise ValueError(
            "routing calibration condition profiles require known exact models"
        )
    if baseline_profile_model == candidate_profile_model:
        raise ValueError("routing calibration requires different arm models")

    quality_meta = payload.get("quality_evaluation")
    if not isinstance(quality_meta, dict) or quality_meta.get("blinded") is not True:
        raise ValueError("routing calibration requires blinded quality evidence")
    pair_count = quality_meta.get("pair_count")
    completed_pairs = quality_meta.get("completed_pairs")
    if (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count <= 0
        or completed_pairs != pair_count
    ):
        raise ValueError("routing calibration requires complete blind grading")

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("routing calibration requires frozen tasks")
    prompts: dict[str, str] = {}
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id") or "").strip()
        prompt = item.get("prompt")
        if task_id and isinstance(prompt, str) and prompt.strip():
            prompts[task_id] = prompt
    if not prompts:
        raise ValueError("routing calibration tasks must contain prompts")

    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("routing calibration requires paired runs")
    pairs: dict[tuple[str, int], dict[str, dict]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("routing calibration run must be an object")
        task_id = str(run.get("task") or "").strip()
        condition = normalize_condition(run.get("condition"))
        trial = run.get("trial", 1)
        if (
            not task_id
            or task_id not in prompts
            or condition not in {"baseline", "token-saver"}
            or isinstance(trial, bool)
            or not isinstance(trial, int)
            or trial <= 0
        ):
            raise ValueError(
                "routing calibration run requires known task, positive trial, and paired condition"
            )
        pair = pairs.setdefault((task_id, trial), {})
        if condition in pair:
            raise ValueError(
                f"duplicate {condition} routing calibration run for {task_id}/{trial}"
            )
        pair[condition] = run

    incomplete = [
        f"{task_id}/{trial}"
        for (task_id, trial), pair in sorted(pairs.items())
        if set(pair) != {"baseline", "token-saver"}
    ]
    if incomplete:
        raise ValueError("unpaired routing calibration runs: " + ", ".join(incomplete))
    if len(pairs) != pair_count:
        raise ValueError(
            "blind quality pair_count does not match routing calibration pairs"
        )

    rates = builtin_rates(require_fresh=True)
    grouped: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for (task_id, trial), pair in sorted(pairs.items()):
        baseline = pair["baseline"]
        candidate = pair["token-saver"]
        baseline_model = _verified_run_model(baseline)
        candidate_model = _verified_run_model(candidate)
        if (
            baseline_model != baseline_profile_model
            or candidate_model != candidate_profile_model
        ):
            raise ValueError(
                "routing calibration run models do not match frozen condition profiles"
            )

        prompt = prompts[task_id]
        task_class, budget, risk_level, _signals, minimum, _reasons = _route_features(
            prompt,
            conservative=True,
        )
        estimated_input = max(1, estimate_tokens(prompt))
        policy_baseline = _policy_baseline_model(
            task=task_class,
            complexity=budget.complexity_tier,
            minimum_capability=minimum,
            rates=rates,
            input_tokens=estimated_input,
            output_tokens=budget.max_tokens,
        )

        baseline_quality = _weighted_quality(baseline.get("quality"))
        candidate_quality = _weighted_quality(candidate.get("quality"))
        for run in (baseline, candidate):
            blocker = run.get("blocker", False)
            if not isinstance(blocker, bool):
                raise ValueError("routing calibration blocker must be boolean")
            if not isinstance(run.get("success"), bool):
                raise ValueError("routing calibration success must be boolean")

        base_q = baseline["quality"]
        cand_q = candidate["quality"]
        quality_pair_ok = (
            candidate.get("blocker") is False
            and float(cand_q["correctness"])
            >= float(base_q["correctness"]) - MAX_QUALITY_DROP
            and float(cand_q["safety"])
            >= float(base_q["safety"]) - MAX_QUALITY_DROP
            and candidate_quality >= baseline_quality - MAX_QUALITY_DROP
        )
        cheaper = (
            all(
                rates[candidate_model][field] <= rates[baseline_model][field]
                for field in FIELDS
            )
            and any(
                rates[candidate_model][field] < rates[baseline_model][field]
                for field in FIELDS
            )
        )
        lower_capability = (
            _CAPABILITY[_MODEL_PROFILES[candidate_model]["capability"]]
            < _CAPABILITY[_MODEL_PROFILES[baseline_model]["capability"]]
        )
        key = (
            task_class,
            budget.complexity_tier,
            risk_level,
            baseline_model,
            candidate_model,
        )
        grouped.setdefault(key, []).append(
            {
                "task": task_id,
                "trial": trial,
                "baseline_success": bool(baseline["success"]),
                "candidate_success": bool(candidate["success"]),
                "quality_pair_ok": quality_pair_ok,
                "baseline_quality": baseline_quality,
                "candidate_quality": candidate_quality,
                "baseline_correctness": float(base_q["correctness"]),
                "candidate_correctness": float(cand_q["correctness"]),
                "baseline_safety": float(base_q["safety"]),
                "candidate_safety": float(cand_q["safety"]),
                "baseline_matches_static_policy": policy_baseline == baseline_model,
                "candidate_strictly_cheaper": cheaper,
                "candidate_lower_capability": lower_capability,
            }
        )

    recommendations: list[dict] = []
    groups: list[dict] = []
    for key, rows in sorted(grouped.items()):
        task_class, complexity, risk_level, baseline_model, candidate_model = key
        pair_total = len(rows)
        task_total = len({row["task"] for row in rows})
        baseline_successes = sum(row["baseline_success"] for row in rows)
        candidate_successes = sum(row["candidate_success"] for row in rows)
        regressions = sum(
            row["baseline_success"] and not row["candidate_success"]
            for row in rows
        )
        baseline_rate = baseline_successes / pair_total
        candidate_rate = candidate_successes / pair_total
        success_preserved = (
            regressions == 0 and candidate_rate >= baseline_rate
        )
        quality_preserved = all(row["quality_pair_ok"] for row in rows)
        baseline_policy_ok = all(
            row["baseline_matches_static_policy"] for row in rows
        )
        cheaper = all(row["candidate_strictly_cheaper"] for row in rows)
        lower_capability = all(row["candidate_lower_capability"] for row in rows)
        sufficient = (
            pair_total >= MIN_CALIBRATION_PAIRS
            and task_total >= MIN_CALIBRATION_TASKS
            and baseline_rate >= MIN_BASELINE_SUCCESS_RATE
        )
        accepted = (
            sufficient
            and success_preserved
            and quality_preserved
            and baseline_policy_ok
            and cheaper
            and lower_capability
        )
        reasons: list[str] = []
        if pair_total < MIN_CALIBRATION_PAIRS:
            reasons.append("insufficient_pairs")
        if task_total < MIN_CALIBRATION_TASKS:
            reasons.append("insufficient_tasks")
        if baseline_rate < MIN_BASELINE_SUCCESS_RATE:
            reasons.append("weak_baseline_success")
        if regressions:
            reasons.append("task_success_regression")
        if candidate_rate < baseline_rate:
            reasons.append("candidate_success_below_baseline")
        if not quality_preserved:
            reasons.append("blind_quality_regression")
        if not baseline_policy_ok:
            reasons.append("baseline_not_static_policy")
        if not cheaper:
            reasons.append("candidate_not_strictly_cheaper")
        if not lower_capability:
            reasons.append("candidate_not_lower_capability")

        group = {
            "task": task_class,
            "complexity_tier": complexity,
            "risk_level": risk_level,
            "baseline_model": baseline_model,
            "candidate_model": candidate_model,
            "pairs": pair_total,
            "tasks": task_total,
            "baseline_success_rate": baseline_rate,
            "candidate_success_rate": candidate_rate,
            "regressions": regressions,
            "success_preserved": success_preserved,
            "quality_preserved": quality_preserved,
            "baseline_matches_static_policy": baseline_policy_ok,
            "candidate_strictly_cheaper": cheaper,
            "candidate_lower_capability": lower_capability,
            "actual_models_verified": True,
            "blinded_quality": True,
            "independent_verification": True,
            "mean_weighted_quality_delta": sum(
                row["candidate_quality"] - row["baseline_quality"] for row in rows
            )
            / pair_total,
            "mean_correctness_delta": sum(
                row["candidate_correctness"] - row["baseline_correctness"]
                for row in rows
            )
            / pair_total,
            "mean_safety_delta": sum(
                row["candidate_safety"] - row["baseline_safety"] for row in rows
            )
            / pair_total,
            "accepted": accepted,
            "rejection_reasons": reasons,
        }
        groups.append(group)
        if accepted:
            recommendations.append(
                {key: value for key, value in group.items() if key not in {
                    "candidate_lower_capability",
                    "accepted",
                    "rejection_reasons",
                }}
            )

    return {
        "schema": ROUTING_CALIBRATION_SCHEMA,
        "source": str(path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "quality_gate": {
            "minimum_pairs": MIN_CALIBRATION_PAIRS,
            "minimum_tasks": MIN_CALIBRATION_TASKS,
            "minimum_baseline_success_rate": MIN_BASELINE_SUCCESS_RATE,
            "maximum_quality_drop": MAX_QUALITY_DROP,
            "success_regressions_allowed": 0,
            "requires_blinded_quality": True,
            "requires_independent_verification": True,
            "requires_transcript_model_confirmation": True,
            "bucket_scope": "exact task + complexity + risk + baseline/candidate model",
        },
        "recommendations": recommendations,
        "groups": groups,
    }


def route_task(
    prompt: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    current_model: str | None = None,
    allowed_models: tuple[str, ...] | list[str] | None = None,
    min_savings: float = 0.05,
    conservative: bool = True,
    task_override: str | None = None,
    calibration: dict | None = None,
) -> ModelRouteDecision:
    """Choose the cheapest statically or quality-gated eligible model."""
    if isinstance(input_tokens, bool) or (
        input_tokens is not None and input_tokens <= 0
    ):
        raise ValueError("input_tokens must be a positive integer")
    if isinstance(output_tokens, bool) or (
        output_tokens is not None and output_tokens <= 0
    ):
        raise ValueError("output_tokens must be a positive integer")
    if not 0 <= min_savings <= 1:
        raise ValueError("min_savings must be between 0 and 1")

    task, budget, risk_level, risk_signals, minimum, requirement_reasons = (
        _route_features(
            prompt,
            task_override=task_override,
            conservative=conservative,
        )
    )
    complexity = budget.complexity_tier

    allowed = tuple(
        dict.fromkeys(
            str(model).strip()
            for model in (allowed_models or DEFAULT_ALLOWED_MODELS)
            if str(model).strip()
        )
    )
    if not allowed:
        raise ValueError("allowed_models must contain at least one model")
    unknown = [model for model in allowed if model not in _MODEL_PROFILES]
    if unknown:
        raise ValueError(
            "no routing capability profile for: " + ", ".join(unknown)
        )

    rates = builtin_rates(require_fresh=True)
    missing_prices = [model for model in allowed if model not in rates]
    if missing_prices:
        raise ValueError(
            "builtin pricing missing routing model(s): "
            + ", ".join(missing_prices)
        )

    input_count = input_tokens or estimate_tokens(prompt)
    input_basis = (
        "caller_supplied_complete_input"
        if input_tokens is not None
        else "local_prompt_text_estimate_only"
    )
    output_count = output_tokens or budget.max_tokens
    policy_baseline = _policy_baseline_model(
        task=task,
        complexity=complexity,
        minimum_capability=minimum,
        rates=rates,
        input_tokens=input_count,
        output_tokens=output_count,
    )
    calibrated = _calibrated_candidates(
        calibration,
        task=task,
        complexity=complexity,
        risk_level=risk_level,
        baseline_model=policy_baseline,
    )

    eligible = tuple(
        model
        for model in allowed
        if model in calibrated
        or _eligible(
            model,
            task=task,
            complexity=complexity,
            minimum_capability=minimum,
        )
    )
    projected = {
        model: _one_turn_cost(
            model,
            rates,
            input_tokens=input_count,
            output_tokens=output_count,
        )
        for model in eligible
    }

    reasons = [
        f"task={task}",
        f"complexity={complexity}",
        f"minimum_capability={minimum}",
        *requirement_reasons,
    ]
    if risk_signals:
        reasons.append("risk_signals=" + ",".join(risk_signals))
    if calibrated:
        reasons.append(
            "quality_gated_candidates=" + ",".join(calibrated)
        )

    calibration_source = (
        str(calibration.get("source_sha256"))
        if calibration and calibration.get("source_sha256")
        else None
    )
    if not eligible:
        return ModelRouteDecision(
            task=task,
            complexity_tier=complexity,
            complexity_score=budget.complexity_score,
            risk_level=risk_level,
            risk_signals=risk_signals,
            minimum_capability=minimum,
            selected_model=None,
            current_model=current_model,
            action="manual",
            allowed_models=allowed,
            eligible_models=(),
            calibrated_models=calibrated,
            calibration_applied=False,
            calibration_source=calibration_source,
            estimated_input_tokens=input_count,
            input_token_basis=input_basis,
            estimated_output_tokens=output_count,
            projected_cost_usd={},
            projected_current_cost_usd=None,
            projected_savings_fraction=None,
            pricing_basis="fresh_input_plus_output_one_turn",
            reasons=tuple(reasons + ["no_allowed_model_satisfies_policy"]),
        )

    selected = min(
        eligible,
        key=lambda model: (projected[model], allowed.index(model)),
    )
    current_cost = None
    savings = None
    action = "recommend"

    if current_model:
        current_rate = rates.get(current_model)
        current_profile_ok = (
            current_model in allowed
            and current_model in _MODEL_PROFILES
            and (
                current_model in calibrated
                or _eligible(
                    current_model,
                    task=task,
                    complexity=complexity,
                    minimum_capability=minimum,
                )
            )
        )
        if current_rate is not None:
            current_cost = _one_turn_cost(
                current_model,
                rates,
                input_tokens=input_count,
                output_tokens=output_count,
            )
        if current_model == selected:
            action = "keep"
        elif not current_profile_ok:
            action = "route"
            reasons.append("current_model_below_policy")
        elif current_cost is not None and current_cost > 0:
            savings = max(
                0.0,
                (current_cost - projected[selected]) / current_cost,
            )
            if savings >= min_savings:
                action = "route"
                reasons.append(f"projected_savings>={min_savings:.0%}")
            else:
                selected = current_model
                action = "keep"
                reasons.append("switch_savings_below_threshold")

    calibration_applied = selected in calibrated
    if calibration_applied:
        reasons.append("quality_gated_calibration_applied")

    return ModelRouteDecision(
        task=task,
        complexity_tier=complexity,
        complexity_score=budget.complexity_score,
        risk_level=risk_level,
        risk_signals=risk_signals,
        minimum_capability=minimum,
        selected_model=selected,
        current_model=current_model,
        action=action,
        allowed_models=allowed,
        eligible_models=eligible,
        calibrated_models=calibrated,
        calibration_applied=calibration_applied,
        calibration_source=calibration_source,
        estimated_input_tokens=input_count,
        input_token_basis=input_basis,
        estimated_output_tokens=output_count,
        projected_cost_usd=projected,
        projected_current_cost_usd=current_cost,
        projected_savings_fraction=savings,
        pricing_basis="fresh_input_plus_output_one_turn",
        reasons=tuple(reasons),
    )


def automatic_model_route(
    root: Path,
    prompt: str,
    *,
    session_id: str | None = None,
    enabled: bool = False,
    mode: str = "advisory",
    current_model: str | None = None,
    allowed_models: tuple[str, ...] | list[str] | None = None,
    min_savings: float = 0.05,
    conservative: bool = True,
    calibration_file: str = DEFAULT_ROUTING_CALIBRATION_FILE,
) -> str | None:
    """Compute, store, and optionally inject a host-neutral routing advisory."""
    if not enabled:
        return None
    normalized_mode = mode.strip().lower()
    if normalized_mode not in ROUTING_MODES:
        raise ValueError(
            "unknown model routing mode; expected one of: "
            + ", ".join(ROUTING_MODES)
        )
    previous = load_state(root, session_id).get("model_route")
    previous = previous if isinstance(previous, dict) else {}
    new_task = looks_like_new_task(prompt)
    detected_task = classify_output_task(prompt)
    inherited_task = (
        str(previous.get("task") or "")
        if detected_task is None and not new_task
        else ""
    )
    calibration_path = Path(calibration_file)
    if not calibration_path.is_absolute():
        calibration_path = root / calibration_path
    calibration: dict = {}
    try:
        calibration = load_routing_calibration(calibration_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        append_event(
            root,
            {
                "kind": "model_route_calibration_rejected",
                "feature": "model_routing",
                "reason": str(exc)[:160],
            },
        )

    try:
        decision = route_task(
            prompt,
            current_model=current_model,
            allowed_models=allowed_models,
            min_savings=min_savings,
            conservative=conservative,
            task_override=(
                inherited_task
                if inherited_task in OUTPUT_TASKS
                else detected_task
            ),
            calibration=calibration,
        )
    except ValueError as exc:
        append_event(
            root,
            {
                "kind": "model_route_unavailable",
                "feature": "model_routing",
                "reason": str(exc)[:160],
            },
        )
        return None

    signature = (
        f"{decision.task}:{decision.complexity_tier}:"
        f"{decision.minimum_capability}:{decision.selected_model}:{decision.action}:"
        f"{decision.calibration_source or 'static'}"
    )
    repeated = previous.get("signature") == signature and not new_task

    def mutate(data: dict) -> None:
        data["model_route"] = {
            "signature": signature,
            "task": decision.task,
            "complexity_tier": decision.complexity_tier,
            "risk_level": decision.risk_level,
            "minimum_capability": decision.minimum_capability,
            "selected_model": decision.selected_model,
            "action": decision.action,
            "pricing_basis": decision.pricing_basis,
            "calibration_applied": decision.calibration_applied,
            "calibration_source": decision.calibration_source,
            "projected_savings_fraction": decision.projected_savings_fraction,
            "projected_selected_cost_usd": (
                decision.projected_cost_usd.get(decision.selected_model)
                if decision.selected_model is not None
                else None
            ),
        }

    update_state(root, mutate, session_id)
    append_event(
        root,
        {
            "kind": "model_route",
            "feature": "model_routing",
            "task": decision.task,
            "complexity_tier": decision.complexity_tier,
            "risk_level": decision.risk_level,
            "selected_model": decision.selected_model,
            "action": decision.action,
            "calibration_applied": decision.calibration_applied,
        },
    )

    if (
        normalized_mode == "observe"
        or repeated
        or decision.selected_model is None
    ):
        return None

    calibration_note = (
        " quality-gated calibration applied;"
        if decision.calibration_applied
        else ""
    )
    return (
        "TOKEN SAVER MODEL ROUTE — host-neutral advisory. "
        "The Claude prompt hook cannot switch the active top-level model itself. "
        "For a model-selectable subagent/orchestrator, use "
        f"{decision.selected_model}. "
        f"action={decision.action}; task={decision.task}; "
        f"complexity={decision.complexity_tier}; risk={decision.risk_level}; "
        f"minimum static capability={decision.minimum_capability};"
        f"{calibration_note} "
        "This is a deterministic routing policy, not a model-quality benchmark."
    )

"""Deterministic capability- and price-aware model routing.

Routing decisions are deliberately conservative. Pricing chooses among models
that already satisfy an explicit capability profile; price never upgrades or
downgrades capability requirements by itself. The Claude prompt hook can inject
advice, while orchestrators that can actually select models should consume the
same decision through the CLI or MCP route_task tool.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from pathlib import Path

from .efficiency.store import append_event
from .estimate import estimate_tokens
from .generation_policy import classify_output_task
from .output_budget import adaptive_output_budget
from .output_saver import OUTPUT_TASKS
from .policy import looks_like_new_task
from .pricing import builtin_rates
from .state import load as load_state
from .state import update as update_state

ROUTING_MODES = ("observe", "advisory")
DEFAULT_ALLOWED_MODELS = (
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-5",
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


def _eligible(
    model: str,
    *,
    task: str,
    complexity: str,
    minimum_capability: str,
) -> bool:
    """Return whether one explicit profile satisfies routing requirements."""
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
) -> ModelRouteDecision:
    """Choose the cheapest model that first satisfies capability rules."""
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

    if task_override is not None:
        task = task_override.strip().lower()
        if task not in OUTPUT_TASKS:
            raise ValueError(f"unknown routing task override: {task_override}")
    else:
        task = classify_output_task(prompt) or "general"
    budget = adaptive_output_budget(prompt, task=task, mode="normal")
    complexity = budget.complexity_tier
    risk_level, risk_signals = _risk(prompt)
    minimum, requirement_reasons = _minimum_capability(
        task,
        complexity,
        risk_level=risk_level,
        conservative=conservative,
    )

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

    eligible = tuple(
        model
        for model in allowed
        if _eligible(
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
            current_model in _MODEL_PROFILES
            and _eligible(
                current_model,
                task=task,
                complexity=complexity,
                minimum_capability=minimum,
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
        f"{decision.minimum_capability}:{decision.selected_model}:{decision.action}"
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
        },
    )

    if (
        normalized_mode == "observe"
        or repeated
        or decision.selected_model is None
    ):
        return None

    return (
        "TOKEN SAVER MODEL ROUTE — host-neutral advisory. "
        "The Claude prompt hook cannot switch the active top-level model itself. "
        "For a model-selectable subagent/orchestrator, use "
        f"{decision.selected_model}. "
        f"action={decision.action}; task={decision.task}; "
        f"complexity={decision.complexity_tier}; risk={decision.risk_level}; "
        f"minimum capability={decision.minimum_capability}. "
        "This is a deterministic routing policy, not a model-quality benchmark."
    )

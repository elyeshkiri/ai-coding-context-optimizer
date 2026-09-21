"""CLI handler for deterministic model-routing decisions."""

from __future__ import annotations

import argparse
import json
import sys

from ..model_routing import DEFAULT_ALLOWED_MODELS, route_task


def model_route_main(argv: list[str]) -> int:
    """Explain or emit one capability- and price-aware model route."""
    parser = argparse.ArgumentParser(prog="token-saver model-route")
    parser.add_argument("prompt")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--current-model")
    parser.add_argument(
        "--allowed-model",
        action="append",
        dest="allowed_models",
        help="repeat to restrict routing candidates",
    )
    parser.add_argument("--min-savings", type=float, default=0.05)
    parser.add_argument(
        "--non-conservative",
        action="store_true",
        help="do not escalate high-risk keywords beyond task/complexity requirements",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        decision = route_task(
            args.prompt,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            current_model=args.current_model,
            allowed_models=args.allowed_models or DEFAULT_ALLOWED_MODELS,
            min_savings=args.min_savings,
            conservative=not args.non_conservative,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = decision.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("TOKEN SAVER MODEL ROUTE")
    print(f"task: {decision.task}")
    print(
        "complexity: "
        f"{decision.complexity_tier} ({decision.complexity_score})"
    )
    print(
        f"risk: {decision.risk_level}; "
        f"minimum capability: {decision.minimum_capability}"
    )
    print(f"action: {decision.action}")
    print(f"selected model: {decision.selected_model or 'manual decision required'}")
    print(
        "pricing basis: fresh input + output for one turn; "
        f"input basis={decision.input_token_basis}"
    )
    if decision.projected_savings_fraction is not None:
        print(
            "projected savings vs current model: "
            f"{decision.projected_savings_fraction:.1%}"
        )
    if decision.projected_cost_usd:
        print("eligible projected costs:")
        for model, cost in sorted(
            decision.projected_cost_usd.items(),
            key=lambda item: (item[1], item[0]),
        ):
            print(f"  {model}: USD {cost:.6f}")
    print(
        "note: capability profiles are conservative Token Saver policy, "
        "not a benchmark ranking of model quality"
    )
    return 0

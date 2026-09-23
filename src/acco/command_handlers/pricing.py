"""CLI inspection for the packaged pricing registry."""

from __future__ import annotations

import argparse
import json
import sys

from ..pricing import builtin_registry, registry_status


def _model_entry(registry: dict, requested: str) -> tuple[str, dict] | None:
    """Resolve only canonical ids or aliases explicitly declared by the registry."""
    for model, entry in registry["models"].items():
        if requested == model or requested in entry["aliases"]:
            return model, entry
    return None


def pricing_main(argv: list[str]) -> int:
    """Inspect packaged pricing rates, provenance, and freshness."""
    parser = argparse.ArgumentParser(prog="acco pricing")
    parser.add_argument("--model", help="show one exact model id or explicit alias")
    parser.add_argument("--max-age-days", type=int)
    parser.add_argument("--require-fresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        registry = builtin_registry()
        status = registry_status(registry, max_age_days=args.max_age_days)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    selected = None
    if args.model:
        selected = _model_entry(registry, args.model)
        if selected is None:
            print(
                f"model not present in builtin pricing registry: {args.model}",
                file=sys.stderr,
            )
            return 2

    if args.json:
        payload = {
            "status": status,
            "models": (
                {selected[0]: selected[1]}
                if selected is not None
                else registry["models"]
            ),
        }
        print(json.dumps(payload, indent=2))
    else:
        print("ACCO PRICING")
        print(
            f"verified: {status['verified_at']} "
            f"({status['age_days']} day(s) ago; "
            f"fresh={'yes' if status['fresh'] else 'no'})"
        )
        print(f"scope: {status['scope']}")
        print(f"source: {status['source_url']}")
        models = (
            {selected[0]: selected[1]}
            if selected is not None
            else registry["models"]
        )
        for model, entry in models.items():
            rates = entry["rates"]
            print(
                f"{model:<24} "
                f"in USD {rates['input']:g}  "
                f"5m USD {rates['cache_write_5m']:g}  "
                f"1h USD {rates['cache_write_1h']:g}  "
                f"hit USD {rates['cache_read']:g}  "
                f"out USD {rates['output']:g}"
            )
            if entry["aliases"]:
                print("  aliases: " + ", ".join(entry["aliases"]))

    return 1 if args.require_fresh and not status["fresh"] else 0

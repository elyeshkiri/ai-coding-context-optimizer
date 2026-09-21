"""Validate packaged pricing freshness and optional live source parity."""

from __future__ import annotations

import argparse
from html import unescape
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from token_saver.pricing import FIELDS, builtin_registry, registry_status  # noqa: E402


def _money_pattern(value: float) -> str:
    """Return a tolerant official-table money pattern for one numeric rate."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if "." in text:
        whole, fraction = text.split(".", 1)
        numeric = re.escape(whole) + r"\." + re.escape(fraction) + r"0*"
    else:
        numeric = re.escape(text) + r"(?:\.0+)?"
    return rf"\$\s*{numeric}\s*/\s*M(?:Tok|TOK)"


def _live_mismatches(registry: dict, source: str) -> list[str]:
    """Return model ids whose official pricing row no longer matches."""
    normalized = unescape(source)
    mismatches: list[str] = []
    for model, entry in registry["models"].items():
        name = re.escape(entry["display_name"])
        rates = entry["rates"]
        pieces = [_money_pattern(rates[field]) for field in FIELDS]
        pattern = name + r"[^\n]{0,1200}?" + r"[^\n]*?".join(pieces)
        if re.search(pattern, normalized, flags=re.IGNORECASE) is None:
            mismatches.append(model)
    return mismatches


def _fetch(url: str) -> str:
    """Fetch the official Markdown pricing source with a bounded timeout."""
    request = Request(
        url,
        headers={"User-Agent": "token-saver-pricing-drift/1.0"},
    )
    with urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    """Validate deterministic freshness and optionally compare the live source."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-days", type=int)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = builtin_registry()
        status = registry_status(registry, max_age_days=args.max_age_days)
    except (OSError, ValueError) as exc:
        print(f"pricing registry invalid: {exc}", file=sys.stderr)
        return 2

    print(
        "pricing registry: "
        f"{status['model_count']} models, verified {status['verified_at']}, "
        f"age {status['age_days']} day(s), limit {status['max_age_days']}"
    )
    if not status["fresh"]:
        print("pricing registry is stale", file=sys.stderr)
        return 1

    if not args.live:
        return 0

    try:
        source = _fetch(registry["source_markdown_url"])
    except OSError as exc:
        print(f"pricing source unavailable: {exc}", file=sys.stderr)
        return 2

    mismatches = _live_mismatches(registry, source)
    if mismatches:
        print(
            "official pricing drift detected for: " + ", ".join(mismatches),
            file=sys.stderr,
        )
        return 1

    print("live official pricing rows match the packaged registry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

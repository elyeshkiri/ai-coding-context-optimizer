"""Deduplication, visibility, fitting, and static-budget helpers."""

from __future__ import annotations

import hashlib
import re

from ..budget import RetrievalPlan
from ..estimate import estimate_tokens

def _fingerprint(section: str) -> str:
    """Handle fingerprint."""
    normal = re.sub(r"\s+", " ", section).strip().encode("utf-8", "replace")
    return hashlib.sha256(normal).hexdigest()


def _visible_symbol_labels(section: str, labels: list[str]) -> list[str]:
    """Keep only labels whose exact source line survived section fitting."""
    marker = "### exact source windows"
    if marker not in section:
        return []
    source = section.split(marker, 1)[1]
    visible: list[str] = []
    for label in labels:
        try:
            line = int(label.rsplit("@", 1)[1])
        except (ValueError, IndexError):
            continue
        if re.search(rf"^\s*{line}\|", source, re.MULTILINE):
            visible.append(label)
    return visible


def _fit_section(section: str, budget: int) -> str:
    """Fit on line boundaries. Never return text estimated above ``budget``."""
    if budget <= 0:
        return ""
    if estimate_tokens(section) <= budget:
        return section
    lines = section.splitlines(keepends=True)
    lo, hi = 0, len(lines)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = "".join(lines[:mid])
        if estimate_tokens(candidate) <= budget:
            lo = mid
        else:
            hi = mid - 1
    if lo <= 2:
        return ""
    out = "".join(lines[:lo]).rstrip() + "\n# … section clipped to token budget\n"
    while out and estimate_tokens(out) > budget:
        lo -= 1
        if lo <= 2:
            return ""
        out = "".join(lines[:lo]).rstrip() + "\n# … section clipped to token budget\n"
    return out


def _static_plan(
    graph_hops: int, closure_max_items: int, context_lines: int,
) -> RetrievalPlan:
    """Handle static plan."""
    return RetrievalPlan(
        seed_limit=6,
        graph_hops=graph_hops,
        closure_items=closure_max_items,
        context_lines=context_lines,
    )



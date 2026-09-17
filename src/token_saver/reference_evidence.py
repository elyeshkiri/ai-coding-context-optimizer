"""Conservative exact-symbol reference evidence for context selection."""
from __future__ import annotations

from typing import Any

from .lexical import terms
from .semantic_ts import resolve_module_path


def _referrers(index: Any) -> dict[tuple[str, str], list[tuple[str, str]]]:
    cached = getattr(index, "_token_saver_symbol_referrers", None)
    if cached is not None:
        return cached
    known = index.records.keys()
    built: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for source_rel, record in index.records.items():
        for ref in record.semantic_refs or []:
            if not isinstance(ref, dict):
                continue
            symbol = str(ref.get("symbol", "")).strip().lower()
            module = str(ref.get("module", ""))
            if not symbol or symbol == "*" or not module:
                continue
            target = resolve_module_path(source_rel, module, known)
            if target is None or target == source_rel:
                continue
            kind = str(ref.get("kind", "semantic-call"))
            built.setdefault((target, symbol), []).append((source_rel, kind))
    for key, values in built.items():
        built[key] = sorted(set(values))
    setattr(index, "_token_saver_symbol_referrers", built)
    return built


def symbol_reference_bonus(
    index: Any,
    target_rel: str,
    symbol_name: str,
    query_terms: set[str],
) -> float:
    """Return a bounded bonus only for exact imported symbols named by the query."""
    name_hits = len(query_terms & set(terms(symbol_name)))
    if not symbol_name or not name_hits:
        return 0.0
    referrers = _referrers(index).get((target_rel, symbol_name.lower()), [])
    if not referrers:
        return 0.0
    strength = max(
        30.0 if kind == "semantic-call" else 22.0 if kind == "reexport" else 18.0
        for _, kind in referrers
    )
    diversity = min(8.0, 2.0 * (len({source for source, _ in referrers}) - 1))
    return strength + 4.0 * name_hits + diversity

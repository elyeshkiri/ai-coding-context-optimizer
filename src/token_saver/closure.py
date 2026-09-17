"""Bounded dependency closure for evidence-complete context packs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .repo_index import RepositoryIndex
from .semantic_ts import resolve_module_path


@dataclass(frozen=True)
class ClosureItem:
    path: str
    distance: int
    reason: str
    source: str
    confidence: float


# This value is consumed both as closure ordering strength and as the packer's
# graph boost. Concrete alias/member-resolved relationships carry substantially
# more evidence than lexical import/call-name coincidences. ``semantic-ref`` is
# deliberately just below a concrete call and is strictly one-hop: assigning or
# otherwise using an imported value is strong evidence for its provider, but not
# permission to recursively pull in that provider's own dependencies.
EDGE_CONFIDENCE = {
    "semantic-call": 3.0,
    "semantic-ref": 2.9,
    "reexport": 0.93,
    "imports": 0.95,
    "imported-by": 0.9,
    "calls": 0.85,
    "calls-symbol": 0.9,
}

_EMITTED_JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
_TS_SOURCE_SUFFIXES = (".ts", ".tsx")


def _semantic_target(index: RepositoryIndex, source: str, module: str) -> str | None:
    """Resolve semantic refs, including TS source imported through emitted JS names.

    NodeNext/ESM TypeScript commonly writes source imports such as
    ``./regexes.js`` even though the repository contains ``regexes.ts`` and the
    compiler emits the ``.js`` file later. The lightweight resolver must mirror
    that convention or exact symbol references disappear from the graph.

    Prefer an exact indexed path first so mixed JS/TS repositories keep their
    real JavaScript target when one exists. Only fall back to ``.ts``/``.tsx``
    when an emitted-JS specifier has no exact match.
    """
    known = index.records.keys()
    target = resolve_module_path(source, module, known)
    if target is not None:
        return target

    suffix = Path(module).suffix.lower()
    if suffix not in _EMITTED_JS_SUFFIXES:
        return None
    stem = module[: -len(suffix)]
    for source_suffix in _TS_SOURCE_SUFFIXES:
        target = resolve_module_path(source, stem + source_suffix, known)
        if target is not None:
            return target
    return None


def _neighbors(index: RepositoryIndex, source: str) -> list[tuple[str, str]]:
    """Return normal graph neighbors plus semantic refs missed by path syntax."""
    out: dict[str, str] = dict(index.neighbors(source))
    record = index.records.get(source)
    if record is None:
        return sorted(out.items())

    for ref in record.semantic_refs or []:
        if not isinstance(ref, dict):
            continue
        module = ref.get("module", "")
        if not isinstance(module, str) or not module:
            continue
        target = _semantic_target(index, source, module)
        if target is None or target == source:
            continue
        kind = ref.get("kind", "semantic-call")
        if not isinstance(kind, str):
            kind = "semantic-call"
        # A concrete call remains stronger than a passive reference when both
        # happen to point at the same provider.
        if target not in out or kind == "semantic-call":
            out[target] = kind
    return sorted(out.items())


def dependency_closure(
    index: RepositoryIndex,
    seeds: list[str],
    *,
    max_hops: int = 2,
    max_items: int = 20,
    min_confidence: float = 0.5,
) -> list[ClosureItem]:
    """Expand relationships breadth-first with confidence decay and hard limits.

    ``semantic-ref`` is intentionally non-transitive. It is strong evidence
    that a query-selected source depends on an exact imported value, so the
    provider deserves a one-hop ranking boost. The provider is not added to the
    next frontier, preventing a value reference from turning into broad closure
    over unrelated downstream dependencies. Concrete ``semantic-call`` edges
    remain transitive because they resolve an actual API invocation.
    """
    if max_hops < 0 or max_items < 0:
        raise ValueError("closure limits must be nonnegative")
    visited = set(seeds)
    frontier = list(dict.fromkeys(seed for seed in seeds if seed in index.records))
    out: list[ClosureItem] = []
    for distance in range(1, max_hops + 1):
        candidates: list[ClosureItem] = []
        for source in frontier:
            for path, edge in _neighbors(index, source):
                if path in visited:
                    continue
                confidence = EDGE_CONFIDENCE.get(edge, 0.6) * (0.75 ** (distance - 1))
                if confidence >= min_confidence:
                    candidates.append(ClosureItem(path, distance, edge, source, confidence))
        candidates.sort(key=lambda item: (-item.confidence, item.path, item.source))
        next_frontier = []
        for item in candidates:
            if item.path in visited:
                continue
            visited.add(item.path)
            out.append(item)
            if item.reason != "semantic-ref":
                next_frontier.append(item.path)
            if len(out) >= max_items:
                return out
        frontier = next_frontier
        if not frontier:
            break
    return out

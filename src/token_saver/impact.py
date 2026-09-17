"""Explain the likely blast radius of changing a file or symbol."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .repo_index import RepositoryIndex, SymbolRecord, build_index


@dataclass(frozen=True)
class ImpactItem:
    path: str
    reason: str
    confidence: float
    symbol: str | None = None
    start_line: int | None = None


@dataclass
class ImpactReport:
    target: str
    matched: list[dict]
    affected: list[ImpactItem]

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "matched": self.matched,
            "affected": [asdict(item) for item in self.affected],
        }


def _tests_for(index: RepositoryIndex, rel: str, symbols: set[str]) -> list[ImpactItem]:
    stem = Path(rel).stem.lower()
    out = []
    for path, lower, tokens in index.test_file_signatures():
        if stem in lower or symbols & tokens:
            out.append(ImpactItem(path, "related-test", 0.85))
    return out


def analyze_impact(
    root: Path, target: str, *, index: RepositoryIndex | None = None,
) -> ImpactReport:
    index = index or build_index(root)
    normalized = target.replace("\\", "/")
    matched: list[tuple[str, SymbolRecord | None]] = []
    if normalized in index.records:
        matched.append((normalized, None))
    else:
        matched.extend(index.find_symbols(target))
    if not matched:
        raise ValueError(f"no indexed file or symbol matches: {target}")

    # A generic symbol name (e.g. a Next.js route's GET/POST export) can
    # appear in many matches. All matches sharing a name have an identical
    # caller list, so scanning it once per match is pure repeated work.
    # Self-exclusion (skip a symbol calling itself) only has to be checked
    # when exactly one match owns that name: with two or more matches for
    # the same name, any caller excluded for one match's own file is still
    # included via the other matches, so the excluded entry always survives
    # in the final (deduplicated-by-key) impacts dict either way.
    sole_owner_by_name: dict[str, tuple[str, str] | None] = {}
    for rel, symbol in matched:
        if symbol is None:
            continue
        key = symbol.name.lower()
        if key in sole_owner_by_name:
            sole_owner_by_name[key] = None
        else:
            sole_owner_by_name[key] = (rel, symbol.name)

    impacts: dict[tuple[str, str, str | None], ImpactItem] = {}
    matched_json = []
    processed_names: set[str] = set()
    for rel, symbol in matched:
        record = index.records[rel]
        symbols = {symbol.name.lower()} if symbol else {name.lower() for name in record.symbols}
        matched_json.append({
            "path": rel,
            "symbol": symbol.name if symbol else None,
            "start_line": symbol.start_line if symbol else None,
            "end_line": symbol.end_line if symbol else None,
        })
        for neighbor, edge in index.neighbors(rel):
            confidence = {
                "imported-by": 0.95, "calls-symbol": 0.9,
                "imports": 0.75, "calls": 0.75,
            }.get(edge, 0.65)
            item = ImpactItem(neighbor, edge, confidence)
            impacts[(neighbor, edge, None)] = item
        for name in symbols:
            if name in processed_names:
                continue
            processed_names.add(name)
            exclude = sole_owner_by_name.get(name)
            for caller_path, caller in index.symbol_callers(name):
                if exclude is not None and (caller_path, caller.name) == exclude:
                    continue
                item = ImpactItem(
                    caller_path, "calls-symbol", 0.95, caller.name, caller.start_line
                )
                impacts[(caller_path, item.reason, caller.name)] = item
                for test in _tests_for(index, caller_path, {caller.name.lower()}):
                    impacts[(test.path, test.reason, None)] = test
        for item in _tests_for(index, rel, symbols):
            impacts[(item.path, item.reason, None)] = item
    affected = sorted(
        impacts.values(),
        key=lambda item: (-item.confidence, item.path, item.reason, item.symbol or "", item.start_line or 0),
    )
    return ImpactReport(target, matched_json, affected)

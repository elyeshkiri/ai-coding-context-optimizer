"""Shared data contracts for the context-packing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RankedFile:
    """Represent one ranked repository file and its retrieval evidence."""

    path: Path
    rel: str
    text: str
    outline: str
    score: float
    reasons: list[str] = field(default_factory=list)
    term_hits: int = 0
    changed: bool = False


@dataclass
class ContextPack:
    """Represent a completed bounded context pack and its evidence metadata."""

    text: str
    estimated_tokens: int
    scanned_files: int
    selected_files: list[str]
    ranked: list[RankedFile]
    selected_symbols: list[str] = field(default_factory=list)
    selected_symbol_identities: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    closure_files: list[str] = field(default_factory=list)
    retrieval_plan: dict[str, int] = field(default_factory=dict)

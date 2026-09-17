"""Public task-aware context packing API.

v1.2 retrieval is index-backed by default. The complete v1.1 implementation is
kept in :mod:`token_saver.legacy_pack` for compatibility helpers and regression
comparison; public signatures remain backward compatible and add opt-in adaptive
budgeting and TypeScript compiler resolution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import legacy_pack as _legacy
from .indexed_pack import build_context_pack_indexed, rank_files_indexed
from .legacy_pack import ContextPack, RankedFile
from .repo_index import RepositoryIndex

# Kept as a module attribute because callers/tests have historically monkey-
# patched this hook. Wrappers resolve it here before entering indexed_pack.
_changed_files = _legacy._changed_files


def rank_files(
    root: Path,
    query: str,
    *,
    use_gitignore: bool = True,
    changed_boost: bool = True,
    index: RepositoryIndex | None = None,
    graph_hops: int = 1,
    session: str | None = None,
    embeddings: bool = False,
    feedback_boost: bool = True,
    closure_max_items: int = 20,
    changed_files: set[str] | None = None,
    priority_files: set[str] | None = None,
    exclude_files: set[str] | None = None,
    restrict_files: set[str] | None = None,
    adaptive_budget: bool = False,
    max_tokens: int = 6000,
    typescript_semantic: bool | None = None,
    strict_semantic: bool = False,
) -> list[RankedFile]:
    if changed_boost and changed_files is None:
        changed_files = _changed_files(Path(root).resolve())
    return rank_files_indexed(
        root,
        query,
        use_gitignore=use_gitignore,
        changed_boost=changed_boost,
        index=index,
        graph_hops=graph_hops,
        session=session,
        embeddings=embeddings,
        feedback_boost=feedback_boost,
        closure_max_items=closure_max_items,
        changed_files=changed_files,
        priority_files=priority_files,
        exclude_files=exclude_files,
        restrict_files=restrict_files,
        adaptive_budget=adaptive_budget,
        max_tokens=max_tokens,
        typescript_semantic=typescript_semantic,
        strict_semantic=strict_semantic,
    )


def build_context_pack(
    root: Path,
    query: str,
    *,
    max_tokens: int = 6000,
    max_files: int = 12,
    context_lines: int = 6,
    use_gitignore: bool = True,
    changed_boost: bool = True,
    graph_hops: int = 1,
    duplicate_threshold: float = 0.92,
    session: str | None = None,
    embeddings: bool = False,
    persist_index: bool = True,
    target_symbol: str | None = None,
    feedback_boost: bool = True,
    closure_max_items: int = 20,
    index: RepositoryIndex | None = None,
    changed_files: set[str] | None = None,
    priority_files: set[str] | None = None,
    exclude_files: set[str] | None = None,
    restrict_files: set[str] | None = None,
    adaptive_budget: bool = False,
    typescript_semantic: bool | None = None,
    strict_semantic: bool = False,
) -> ContextPack:
    if changed_boost and changed_files is None:
        changed_files = _changed_files(Path(root).resolve())
    return build_context_pack_indexed(
        root,
        query,
        max_tokens=max_tokens,
        max_files=max_files,
        context_lines=context_lines,
        use_gitignore=use_gitignore,
        changed_boost=changed_boost,
        graph_hops=graph_hops,
        duplicate_threshold=duplicate_threshold,
        session=session,
        embeddings=embeddings,
        persist_index=persist_index,
        target_symbol=target_symbol,
        feedback_boost=feedback_boost,
        closure_max_items=closure_max_items,
        index=index,
        changed_files=changed_files,
        priority_files=priority_files,
        exclude_files=exclude_files,
        restrict_files=restrict_files,
        adaptive_budget=adaptive_budget,
        typescript_semantic=typescript_semantic,
        strict_semantic=strict_semantic,
    )


def __getattr__(name: str) -> Any:
    """Expose legacy private helpers for integrations that imported them."""
    return getattr(_legacy, name)

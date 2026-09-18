"""Inspection surface for the same retrieval pipeline used by context packing."""
from __future__ import annotations

from pathlib import Path

from .estimate import estimate_tokens
from .lexical import fuzzy_symbol_terms, symbol_terms, terms
from .pack import (
    _file_section,
    _fit_section,
    _read_source,
    _visible_symbol_labels,
    rank_files,
)
from .repo_index import RepositoryIndex, build_index


def browse_context(
    root: Path,
    query: str,
    *,
    max_files: int = 8,
    preview_tokens: int = 350,
    detail_tokens: int = 1200,
    changed_boost: bool = True,
    index: RepositoryIndex | None = None,
) -> dict:
    """Return ranked context candidates with source-backed symbol previews.

    This deliberately reuses rank_files and _file_section rather than
    maintaining a second search engine. The browser therefore exposes what
    the packer would actually consider, including graph reasons, redaction,
    symbol windows, and the same visible-source symbol accounting.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if max_files <= 0:
        raise ValueError("max_files must be positive")
    if preview_tokens <= 0 or detail_tokens <= 0:
        raise ValueError("preview/detail token budgets must be positive")

    root = root.resolve()
    index = index or build_index(root)
    ranked = rank_files(
        root,
        query,
        changed_boost=changed_boost,
        index=index,
    )
    query_terms = set(terms(query))
    symbol_query = set(symbol_terms(query))
    files: list[dict] = []

    for rank, item in enumerate(ranked[:max_files], start=1):
        source = _read_source(item.path)
        if source is None:
            continue
        item.text = source
        section, labels, identities, redactions = _file_section(
            item, query_terms, 4, index, None,
        )
        record = index.records.get(item.rel)
        vocabulary: set[str] = set()
        if record is not None:
            for symbol in record.definitions or []:
                vocabulary.update(terms(symbol.name + " " + symbol.signature))
        fuzzy = fuzzy_symbol_terms(symbol_query, vocabulary)
        preview = _fit_section(section, preview_tokens)
        detail = _fit_section(section, detail_tokens)
        visible = _visible_symbol_labels(detail, labels)

        files.append({
            "rank": rank,
            "path": item.rel,
            "score": round(item.score, 4),
            "reasons": item.reasons,
            "symbols": visible,
            "qualified_symbols": _visible_symbol_labels(detail, identities),
            "fuzzy_corrections": {
                source_term: {"term": target, "similarity": round(ratio, 3)}
                for source_term, (target, ratio) in fuzzy.items()
            },
            "preview": preview,
            "detail": detail,
            "preview_tokens": estimate_tokens(preview),
            "redactions": redactions,
        })

    return {
        "query": query,
        "files": files,
        "candidate_count": len(files),
    }

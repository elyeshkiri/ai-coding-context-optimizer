"""Hybrid retrieval fusion primitives for ACCO retrieval vNext.

The semantic index discovers candidate source ranges but never becomes source
authority. These helpers combine semantic rank with already-measured lexical
and structural evidence without introducing generated query terms.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

from .lexical import terms

DEFAULT_FUSION_K = 40.0
DEFAULT_SEMANTIC_RANK_WEIGHT = 700.0
DEFAULT_LEXICAL_CONFIRMATION_WEIGHT = 1.75
DEFAULT_SIMILARITY_WEIGHT = 8.0
DEFAULT_VIEW_WEIGHT = 1.25


@dataclass(frozen=True)
class HybridRetrievalEvidence:
    """Describe bounded file-level hybrid retrieval evidence."""

    semantic_rank: int
    lexical_rank: int
    semantic_score: float
    term_hits: int
    query_views: int
    path_overlap: int
    boost: float

    def reason(self) -> str:
        """Render compact deterministic ranking evidence."""
        return (
            "hybrid-vnext:"
            f"semantic-rank={self.semantic_rank}:"
            f"lexical-rank={self.lexical_rank}:"
            f"score={self.semantic_score:.3f}:"
            f"term-hits={self.term_hits}:"
            f"views={self.query_views}:"
            f"path-overlap={self.path_overlap}:"
            f"boost={self.boost:.3f}"
        )


def configured_semantic_model(default: str) -> str:
    """Return the explicit local embedding model or the supplied default.

    This intentionally does not download or select a larger model on its own.
    Operators may point sentence-transformers at a code-specialized model with
    ACCO_SEMANTIC_MODEL and evaluate it on a fresh holdout.
    """
    value = os.environ.get("ACCO_SEMANTIC_MODEL", "").strip()
    return value or default


def reciprocal_rank(rank: int, *, k: float = DEFAULT_FUSION_K) -> float:
    """Return a bounded reciprocal-rank contribution."""
    if rank <= 0:
        return 0.0
    if k <= 0:
        raise ValueError("fusion k must be positive")
    return 1.0 / (k + rank)


def path_query_overlap(query: str, rel: str) -> int:
    """Count exact normalized query terms represented in a repository path."""
    query_terms = set(terms(query))
    if not query_terms:
        return 0
    return len(query_terms & set(terms(rel)))


def hybrid_file_boost(
    *,
    query: str,
    rel: str,
    semantic_rank: int,
    lexical_rank: int,
    semantic_score: float,
    term_hits: int,
    query_views: int,
) -> HybridRetrievalEvidence:
    """Fuse semantic discovery with lexical corroboration without vetoing rescue.

    Semantic rank remains the primary contribution. Lexical/path evidence adds a
    small rank-independent corroboration bonus when it exists, while a zero-overlap semantic hit
    can still be rescued. The total is deliberately bounded so explicit
    structural authority remains stronger than semantic evidence.
    """
    semantic_rrf = reciprocal_rank(semantic_rank)
    overlap = path_query_overlap(query, rel)

    rank_component = DEFAULT_SEMANTIC_RANK_WEIGHT * semantic_rrf
    similarity_component = DEFAULT_SIMILARITY_WEIGHT * max(0.0, semantic_score)
    lexical_component = DEFAULT_LEXICAL_CONFIRMATION_WEIGHT * math.log1p(max(0, term_hits))
    view_component = DEFAULT_VIEW_WEIGHT * max(0, min(3, query_views) - 1)
    path_component = min(3.0, 0.75 * overlap)

    boost = min(
        34.0,
        rank_component
        + similarity_component
        + lexical_component
        + view_component
        + path_component,
    )
    return HybridRetrievalEvidence(
        semantic_rank=semantic_rank,
        lexical_rank=lexical_rank,
        semantic_score=semantic_score,
        term_hits=term_hits,
        query_views=query_views,
        path_overlap=overlap,
        boost=boost,
    )

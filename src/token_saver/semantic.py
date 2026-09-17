"""Optional local embedding reranking.

The core package has no ML dependency. When requested, this module uses a local
Sentence Transformers model to score compact candidate representations. The
model may be downloaded by sentence-transformers on first use depending on its
configuration; subsequent inference can run locally.
"""

from __future__ import annotations

DEFAULT_SEMANTIC_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def embedding_scores(query: str, documents: list[str], model_name: str | None = None) -> list[float]:
    if not documents:
        return []
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "semantic reranking requires the optional dependency: "
            "python -m pip install 'token-saver[semantic]'"
        ) from exc

    model = SentenceTransformer(model_name or DEFAULT_SEMANTIC_MODEL)
    vectors = model.encode(
        [query, *documents],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_vec = vectors[0]
    scores: list[float] = []
    for vector in vectors[1:]:
        scores.append(float((query_vec * vector).sum()))
    return scores

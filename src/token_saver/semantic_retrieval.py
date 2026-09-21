"""Persistent chunk-level semantic retrieval with deterministic lexical fusion.

This module stores vectors and source coordinates, never source text. Final
context rendering remains the responsibility of the exact-source packing
pipeline, so semantic retrieval can discover candidates without becoming a
lossy editing source.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sqlite3
from typing import Protocol

from .lexical import terms
from .repo_index import RepositoryIndex
from .state import state_dir

SEMANTIC_SCHEMA = 2
DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_CHUNK_LINES = 64
DEFAULT_CHUNK_OVERLAP = 12
DEFAULT_TOP_K = 96
DEFAULT_MIN_SCORE = 0.12
MAX_EMBED_CHARS = 12000
SYMBOL_CONTEXT_LINES = 3
MAX_SYMBOL_CHUNK_LINES = 96
MAX_QUERY_VIEWS = 3
QUERY_VIEW_MIN_TERMS = 5
QUERY_VIEW_LONG_TERMS = 24
QUERY_FUSION_K = 60.0


def _normalize_query_view(value: str) -> str:
    """Collapse whitespace without inventing or rewriting query vocabulary."""
    return " ".join(value.split()).strip()


def _semantic_query_views(
    query: str,
    *,
    max_views: int = MAX_QUERY_VIEWS,
) -> list[str]:
    """Return bounded exact-vocabulary semantic views of one user query.

    The full query is always first. Long multi-clause prompts additionally
    contribute their strongest clauses. A long single-clause prompt falls back
    to overlapping front/back word windows. Every added view consists only of
    words already present in the original query, so this stage cannot inject
    repository identifiers or model-generated expansion terms.
    """
    if max_views <= 0:
        raise ValueError("semantic max query views must be positive")
    normalized = _normalize_query_view(query)
    if not normalized:
        return []

    views = [normalized]
    if max_views == 1:
        return views

    lexical_terms = terms(normalized)
    if len(set(lexical_terms)) < QUERY_VIEW_MIN_TERMS:
        return views

    raw_parts = re.split(r"(?:\n+|(?<=[.!?;])\s+)", query)
    candidates: list[tuple[int, int, int, str]] = []
    seen = {normalized.casefold()}
    for position, raw in enumerate(raw_parts):
        value = _normalize_query_view(raw)
        if not value or value.casefold() in seen:
            continue
        distinct = len(set(terms(value)))
        if distinct < QUERY_VIEW_MIN_TERMS or len(value) < 24:
            continue
        candidates.append((-distinct, -len(value), position, value))

    for _neg_terms, _neg_len, _position, value in sorted(candidates):
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        views.append(value)
        if len(views) >= max_views:
            return views

    # A single long sentence can still contain semantically distinct beginning
    # and ending concepts. Use overlapping exact word windows rather than an
    # inferred summary or generated rewrite.
    if len(views) == 1 and len(lexical_terms) >= QUERY_VIEW_LONG_TERMS:
        words = normalized.split()
        window_size = max(12, math.ceil(len(words) * 0.60))
        if window_size < len(words):
            for window in (words[:window_size], words[-window_size:]):
                value = " ".join(window)
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                views.append(value)
                if len(views) >= max_views:
                    break
    return views


def _semantic_hit_key(hit: SemanticHit) -> tuple[str, int, int, str]:
    """Return stable identity for one semantic chunk hit across query views."""
    return (
        hit.path,
        hit.start_line,
        hit.end_line,
        hit.symbol or "",
    )


def _fuse_query_view_hits(
    hit_lists: list[list[SemanticHit]],
    *,
    top_k: int,
) -> list[SemanticHit]:
    """Fuse per-view chunk ranks with weighted reciprocal-rank fusion."""
    if not hit_lists:
        return []
    if len(hit_lists) == 1:
        return hit_lists[0][:top_k]

    aggregated: dict[
        tuple[str, int, int, str],
        dict[str, object],
    ] = {}
    for view_index, hits in enumerate(hit_lists):
        weight = 1.0 if view_index == 0 else 0.90
        for hit in hits:
            key = _semantic_hit_key(hit)
            state = aggregated.setdefault(
                key,
                {
                    "rrf": 0.0,
                    "best_score": hit.score,
                    "best_rank": hit.rank,
                    "hit": hit,
                    "views": set(),
                },
            )
            state["rrf"] = float(state["rrf"]) + (
                weight / (QUERY_FUSION_K + hit.rank)
            )
            state["best_rank"] = min(int(state["best_rank"]), hit.rank)
            if hit.score > float(state["best_score"]):
                state["best_score"] = hit.score
                state["hit"] = hit
            views = state["views"]
            assert isinstance(views, set)
            views.add(view_index)

    ordered = sorted(
        aggregated.values(),
        key=lambda state: (
            -float(state["rrf"]),
            -float(state["best_score"]),
            int(state["best_rank"]),
            _semantic_hit_key(state["hit"]),
        ),
    )
    fused: list[SemanticHit] = []
    for rank, state in enumerate(ordered[:top_k], start=1):
        best = state["hit"]
        assert isinstance(best, SemanticHit)
        views = state["views"]
        assert isinstance(views, set)
        fused.append(
            SemanticHit(
                path=best.path,
                start_line=best.start_line,
                end_line=best.end_line,
                score=float(state["best_score"]),
                rank=rank,
                symbol=best.symbol,
                query_views=len(views),
            )
        )
    return fused


class Encoder(Protocol):
    """Minimal sentence-transformer-compatible encoder contract."""

    def encode(self, sentences, *, normalize_embeddings: bool = True):
        """Return one vector for each supplied sentence."""
        ...


@dataclass(frozen=True)
class SemanticHit:
    """One chunk-level semantic retrieval hit."""

    path: str
    start_line: int
    end_line: int
    score: float
    rank: int
    symbol: str | None = None
    query_views: int = 1

    def evidence(self) -> str:
        """Return compact human-readable ranking evidence."""
        symbol = f":{self.symbol}" if self.symbol else ""
        return (
            f"semantic-chunk:{self.rank}:{self.score:.3f}:"
            f"{self.path}{symbol}@L{self.start_line}-L{self.end_line}"
        )


@dataclass(frozen=True)
class SemanticIndexStats:
    """Observable persistent semantic-index state."""

    files: int
    chunks: int
    dimensions: int
    model: str
    model_revision: str | None
    backend: str
    path: str

    def to_dict(self) -> dict:
        """Return JSON-compatible semantic-index status."""
        return {
            "schema": SEMANTIC_SCHEMA,
            "files": self.files,
            "chunks": self.chunks,
            "dimensions": self.dimensions,
            "model": self.model,
            "model_revision": self.model_revision,
            "backend": self.backend,
            "path": self.path,
        }


def _project_id(root: Path) -> str:
    """Return an opaque stable project identifier."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def _model_revision() -> str | None:
    """Return the optional immutable local embedding-model revision."""
    return os.environ.get("TOKEN_SAVER_SEMANTIC_MODEL_REVISION") or None


def _model_id(model: str, revision: str | None = None) -> str:
    """Return a filesystem-safe model plus revision identity."""
    identity = f"{model}\0{revision or ''}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def semantic_index_path(
    root: Path,
    model: str = DEFAULT_MODEL,
    revision: str | None = None,
) -> Path:
    """Return the private SQLite semantic-index path for model weights."""
    resolved_revision = _model_revision() if revision is None else revision
    return (
        state_dir()
        / "semantic-index"
        / _project_id(root)
        / f"{_model_id(model, resolved_revision)}.sqlite3"
    )


def _ann_path(database_path: Path) -> Path:
    """Return the optional persisted HNSW sidecar path."""
    return database_path.with_suffix(".hnsw")


def _hnswlib():
    """Return optional hnswlib module without making it a hard dependency."""
    try:
        import hnswlib
    except ImportError:
        return None
    return hnswlib


def _effective_backend(path: Path, meta: dict[str, str]) -> str:
    """Return the backend usable in the current process."""
    if (
        meta.get("ann_backend") == "hnsw"
        and _ann_path(path).is_file()
        and _hnswlib() is not None
    ):
        return "hnsw"
    return "sqlite-cosine"


def _load_encoder(model: str) -> Encoder:
    """Load one already-downloaded local sentence-transformer model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "hybrid semantic retrieval requires: "
            "pip install 'claude-token-saver[embeddings]'"
        ) from exc
    try:
        revision = _model_revision()
        return SentenceTransformer(
            model,
            revision=revision,
            local_files_only=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"local embedding model {model} is not downloaded"
        ) from exc


def _vector(value) -> list[float]:
    """Normalize common encoder vector containers to finite floats."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    out = [float(item) for item in value]
    if not out or not all(math.isfinite(item) for item in out):
        raise ValueError("embedding encoder returned an invalid vector")
    return out


def _encode(encoder: Encoder, texts: list[str]) -> list[list[float]]:
    """Encode texts through one normalized local-only model call."""
    if not texts:
        return []
    raw = encoder.encode(texts, normalize_embeddings=True)
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    return [_vector(value) for value in raw]


def _cosine(left: list[float], right: list[float]) -> float:
    """Return cosine similarity, accepting pre-normalized or raw vectors."""
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _symbol_for_range(record, start: int, end: int) -> str | None:
    """Return the narrowest indexed symbol overlapping a chunk."""
    matches = [
        symbol
        for symbol in record.definitions or []
        if symbol.start_line <= end and symbol.end_line >= start
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda symbol: (
            max(1, symbol.end_line - symbol.start_line),
            symbol.start_line,
            symbol.name,
        )
    )
    return matches[0].qualified or matches[0].name


def _append_semantic_chunk(
    chunks: list[tuple[int, int, str, str | None]],
    seen: set[tuple[int, int, str]],
    *,
    rel: str,
    lines: list[str],
    start: int,
    end: int,
    symbol_record=None,
) -> None:
    """Append one deduplicated exact-source chunk with structural metadata."""
    if not lines:
        return
    start = max(1, min(start, len(lines)))
    end = max(start, min(end, len(lines)))
    symbol = None
    metadata = [f"path: {rel}"]
    if symbol_record is not None:
        symbol = symbol_record.qualified or symbol_record.name
        metadata.append(f"symbol: {symbol}")
        if symbol_record.kind:
            metadata.append(f"kind: {symbol_record.kind}")
        if symbol_record.parent:
            metadata.append(f"parent: {symbol_record.parent}")
        if symbol_record.signature:
            metadata.append(f"signature: {symbol_record.signature}")
    body = "\n".join(lines[start - 1 : end])
    rendered = ("\n".join(metadata) + "\n" + body)[:MAX_EMBED_CHARS]
    identity = (start, end, rendered)
    if identity in seen:
        return
    seen.add(identity)
    chunks.append((start, end, rendered, symbol))


def _symbol_chunks(
    rel: str,
    lines: list[str],
    record,
    *,
    chunk_lines: int,
    overlap: int,
    chunks: list[tuple[int, int, str, str | None]],
    seen: set[tuple[int, int, str]],
) -> None:
    """Add symbol-aware chunks that keep signatures and bodies semantically tight."""
    for symbol in sorted(
        record.definitions or [],
        key=lambda item: (item.start_line, item.end_line, item.name),
    ):
        raw_start = max(1, symbol.start_line - SYMBOL_CONTEXT_LINES)
        raw_end = min(len(lines), symbol.end_line + SYMBOL_CONTEXT_LINES)
        if raw_end < raw_start:
            continue
        if raw_end - raw_start + 1 <= MAX_SYMBOL_CHUNK_LINES:
            _append_semantic_chunk(
                chunks,
                seen,
                rel=rel,
                lines=lines,
                start=raw_start,
                end=raw_end,
                symbol_record=symbol,
            )
            continue

        # Large functions/classes are split into overlapping windows but retain
        # the same structural metadata, which gives the encoder both intent
        # vocabulary (signature/parent/kind) and local implementation context.
        step = max(1, chunk_lines - overlap)
        for start in range(raw_start, raw_end + 1, step):
            end = min(raw_end, start + chunk_lines - 1)
            _append_semantic_chunk(
                chunks,
                seen,
                rel=rel,
                lines=lines,
                start=start,
                end=end,
                symbol_record=symbol,
            )
            if end >= raw_end:
                break


def _chunk_source(
    rel: str,
    text: str,
    record,
    *,
    chunk_lines: int,
    overlap: int,
) -> list[tuple[int, int, str, str | None]]:
    """Create structural plus sliding semantic chunks from exact source bytes.

    Symbol-aware chunks are emitted first so function/class signatures, parent
    identity, declaration kind, and implementation body stay together. Sliding
    windows remain as a language-agnostic fallback for module-level behavior,
    prose, configuration, and parser gaps.
    """
    if chunk_lines <= 0:
        raise ValueError("semantic chunk_lines must be positive")
    if overlap < 0 or overlap >= chunk_lines:
        raise ValueError("semantic overlap must satisfy 0 <= overlap < chunk_lines")
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[tuple[int, int, str, str | None]] = []
    seen: set[tuple[int, int, str]] = set()
    _symbol_chunks(
        rel,
        lines,
        record,
        chunk_lines=chunk_lines,
        overlap=overlap,
        chunks=chunks,
        seen=seen,
    )

    step = chunk_lines - overlap
    for offset in range(0, len(lines), step):
        start = offset + 1
        end = min(len(lines), offset + chunk_lines)
        symbol = _symbol_for_range(record, start, end)
        symbol_record = next(
            (
                candidate
                for candidate in record.definitions or []
                if (candidate.qualified or candidate.name) == symbol
            ),
            None,
        )
        _append_semantic_chunk(
            chunks,
            seen,
            rel=rel,
            lines=lines,
            start=start,
            end=end,
            symbol_record=symbol_record,
        )
        if end >= len(lines):
            break
    return chunks


def _connect(path: Path) -> sqlite3.Connection:
    """Open and initialize one private semantic SQLite database."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            file_digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            file_digest TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            symbol TEXT,
            vector_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        CREATE TABLE IF NOT EXISTS query_vectors (
            query_hash TEXT PRIMARY KEY,
            query_text_sha256 TEXT NOT NULL,
            vector_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ann_labels (
            label INTEGER PRIMARY KEY,
            chunk_id TEXT NOT NULL UNIQUE
        );
        """
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return conn


def _meta(conn: sqlite3.Connection) -> dict[str, str]:
    """Return semantic-index metadata."""
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("SELECT key, value FROM meta")
    }


def _write_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Upsert semantic-index metadata."""
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        sorted(values.items()),
    )


class SemanticVectorIndex:
    """Persistent chunk vector index derived from a RepositoryIndex."""

    def __init__(
        self,
        root: Path,
        index: RepositoryIndex,
        *,
        model: str = DEFAULT_MODEL,
        chunk_lines: int = DEFAULT_CHUNK_LINES,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
        encoder: Encoder | None = None,
    ):
        """Bind semantic persistence to one repository/index/model contract."""
        self.root = root.resolve()
        self.index = index
        self.model = model
        self.model_revision = _model_revision()
        self.chunk_lines = chunk_lines
        self.overlap = overlap
        self._encoder = encoder
        self.path = semantic_index_path(
            self.root,
            model,
            self.model_revision,
        )

    def _get_encoder(self) -> Encoder:
        """Load the local encoder lazily."""
        if self._encoder is None:
            self._encoder = _load_encoder(self.model)
        return self._encoder

    def _reset_if_incompatible(self, conn: sqlite3.Connection) -> None:
        """Discard vectors when schema/model/chunking semantics change."""
        expected = {
            "schema": str(SEMANTIC_SCHEMA),
            "model": self.model,
            "model_revision": self.model_revision or "",
            "chunk_lines": str(self.chunk_lines),
            "overlap": str(self.overlap),
        }
        current = _meta(conn)
        if current and any(current.get(key) != value for key, value in expected.items()):
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM query_vectors")
            conn.execute("DELETE FROM ann_labels")
            conn.execute("DELETE FROM meta")
            try:
                _ann_path(self.path).unlink()
            except FileNotFoundError:
                pass
        _write_meta(conn, expected)

    def _ann_signature(self, conn: sqlite3.Connection) -> str:
        """Hash ordered chunk identities to version the ANN sidecar."""
        digest = hashlib.sha256()
        for row in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id"):
            digest.update(str(row["chunk_id"]).encode())
            digest.update(b"\n")
        return digest.hexdigest()

    def _rebuild_ann(self, conn: sqlite3.Connection, dimensions: int) -> str:
        """Rebuild optional HNSW acceleration from authoritative SQLite vectors."""
        library = _hnswlib()
        if library is None or dimensions <= 0:
            try:
                _ann_path(self.path).unlink()
            except FileNotFoundError:
                pass
            conn.execute("DELETE FROM ann_labels")
            _write_meta(conn, {"ann_signature": "", "ann_backend": "sqlite-cosine"})
            return "sqlite-cosine"

        rows = list(
            conn.execute(
                "SELECT chunk_id, vector_json FROM chunks ORDER BY chunk_id"
            )
        )
        if not rows:
            conn.execute("DELETE FROM ann_labels")
            try:
                _ann_path(self.path).unlink()
            except FileNotFoundError:
                pass
            _write_meta(conn, {"ann_signature": "", "ann_backend": "sqlite-cosine"})
            return "sqlite-cosine"

        vectors = [
            [float(value) for value in json.loads(row["vector_json"])]
            for row in rows
        ]
        ann = library.Index(space="cosine", dim=dimensions)
        ann.init_index(
            max_elements=len(rows),
            ef_construction=120,
            M=16,
        )
        labels = list(range(len(rows)))
        ann.add_items(vectors, labels)
        ann.set_ef(min(max(64, len(rows)), 256))
        ann.save_index(str(_ann_path(self.path)))
        conn.execute("DELETE FROM ann_labels")
        conn.executemany(
            "INSERT INTO ann_labels(label, chunk_id) VALUES (?, ?)",
            [(label, str(row["chunk_id"])) for label, row in zip(labels, rows)],
        )
        _write_meta(
            conn,
            {
                "ann_signature": self._ann_signature(conn),
                "ann_backend": "hnsw",
            },
        )
        return "hnsw"

    def _ensure_ann(self, conn: sqlite3.Connection, dimensions: int) -> str:
        """Keep optional ANN acceleration synchronized with authoritative vectors."""
        meta = _meta(conn)
        signature = self._ann_signature(conn)
        if _hnswlib() is None:
            return "sqlite-cosine"
        if (
            _hnswlib() is not None
            and _ann_path(self.path).is_file()
            and meta.get("ann_backend") == "hnsw"
            and meta.get("ann_signature") == signature
        ):
            return "hnsw"
        return self._rebuild_ann(conn, dimensions)

    def sync(self) -> SemanticIndexStats:
        """Incrementally embed changed files and remove deleted-file vectors."""
        conn = _connect(self.path)
        try:
            self._reset_if_incompatible(conn)
            current_paths = set(self.index.records)
            existing = {
                str(row["path"]): str(row["file_digest"])
                for row in conn.execute(
                    "SELECT path, file_digest FROM files"
                )
            }
            stale_paths = sorted(set(existing) - current_paths)
            for stale in stale_paths:
                conn.execute("DELETE FROM chunks WHERE path = ?", (stale,))
                conn.execute("DELETE FROM files WHERE path = ?", (stale,))

            pending: list[tuple[str, str, int, int, str | None, str]] = []
            changed_paths: list[str] = []
            for rel, record in sorted(self.index.records.items()):
                if existing.get(rel) == record.digest:
                    continue
                path = self.root / rel
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    raise RuntimeError(
                        f"unable to read indexed source for semantic refresh: {rel}"
                    ) from exc
                current_digest = hashlib.sha256(
                    text.encode("utf-8", "replace")
                ).hexdigest()
                if current_digest != record.digest:
                    raise RuntimeError(
                        f"source changed after repository indexing: {rel}; "
                        "refresh the repository index and retry"
                    )
                changed_paths.append(rel)
                for start, end, body, symbol in _chunk_source(
                    rel,
                    text,
                    record,
                    chunk_lines=self.chunk_lines,
                    overlap=self.overlap,
                ):
                    body_digest = hashlib.sha256(body.encode()).hexdigest()
                    chunk_id = hashlib.sha256(
                        (
                            f"{rel}\0{record.digest}\0{start}\0{end}\0"
                            f"{body_digest}"
                        ).encode()
                    ).hexdigest()
                    pending.append(
                        (chunk_id, rel, record.digest, start, end, symbol, body)
                    )

            vectors = (
                _encode(
                    self._get_encoder(),
                    [item[-1] for item in pending],
                )
                if pending
                else []
            )
            if pending and len(vectors) != len(pending):
                raise RuntimeError("embedding encoder returned the wrong batch size")
            dimensions = len(vectors[0]) if vectors else int(_meta(conn).get("dimensions", "0"))
            if vectors and any(len(vector) != dimensions for vector in vectors):
                raise RuntimeError("embedding encoder returned inconsistent dimensions")

            for rel in changed_paths:
                conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
                record = self.index.records[rel]
                conn.execute(
                    "INSERT OR REPLACE INTO files(path, file_digest) VALUES (?, ?)",
                    (rel, record.digest),
                )
            for item, vector in zip(pending, vectors):
                chunk_id, rel, digest, start, end, symbol, _body = item
                conn.execute(
                    """
                    INSERT INTO chunks(
                        chunk_id, path, file_digest, start_line, end_line, symbol, vector_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        rel,
                        digest,
                        start,
                        end,
                        symbol,
                        json.dumps(vector, separators=(",", ":")),
                    ),
                )
            if dimensions:
                _write_meta(conn, {"dimensions": str(dimensions)})
            if stale_paths or changed_paths:
                self._rebuild_ann(conn, dimensions)
            else:
                self._ensure_ann(conn, dimensions)
            conn.commit()
            return self.status(conn=conn)
        finally:
            conn.close()

    def _query_vector(self, conn: sqlite3.Connection, query: str) -> list[float]:
        """Return a persistent query vector keyed by exact query and model."""
        digest = hashlib.sha256(query.encode()).hexdigest()
        key = hashlib.sha256(
            f"{self.model}\0{self.model_revision or ''}\0{digest}".encode()
        ).hexdigest()
        row = conn.execute(
            "SELECT query_text_sha256, vector_json FROM query_vectors WHERE query_hash = ?",
            (key,),
        ).fetchone()
        if row is not None and row["query_text_sha256"] == digest:
            return [float(value) for value in json.loads(row["vector_json"])]
        vector = _encode(self._get_encoder(), [query])[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO query_vectors(query_hash, query_text_sha256, vector_json)
            VALUES (?, ?, ?)
            """,
            (key, digest, json.dumps(vector, separators=(",", ":"))),
        )
        conn.commit()
        return vector

    def _query_ann(
        self,
        conn: sqlite3.Connection,
        query_vector: list[float],
        *,
        top_k: int,
        min_score: float,
    ) -> list[SemanticHit] | None:
        """Return ANN hits when a synchronized HNSW sidecar is available."""
        library = _hnswlib()
        meta = _meta(conn)
        dimensions = int(meta.get("dimensions", "0"))
        if (
            library is None
            or dimensions <= 0
            or meta.get("ann_backend") != "hnsw"
            or meta.get("ann_signature") != self._ann_signature(conn)
            or not _ann_path(self.path).is_file()
        ):
            return None
        count = int(conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"])
        if count <= 0:
            return []
        ann = library.Index(space="cosine", dim=dimensions)
        ann.load_index(str(_ann_path(self.path)), max_elements=count)
        ann.set_ef(min(max(64, top_k * 3), max(64, count)))
        labels, distances = ann.knn_query(
            [query_vector],
            k=min(top_k, count),
        )
        label_values = [int(value) for value in labels[0]]
        distance_values = [float(value) for value in distances[0]]
        mapping = {
            int(row["label"]): str(row["chunk_id"])
            for row in conn.execute(
                "SELECT label, chunk_id FROM ann_labels"
            )
        }
        hits: list[SemanticHit] = []
        for label, distance in zip(label_values, distance_values):
            chunk_id = mapping.get(label)
            if chunk_id is None:
                continue
            score = 1.0 - distance
            if score < min_score:
                continue
            row = conn.execute(
                """
                SELECT path, start_line, end_line, symbol
                FROM chunks WHERE chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            hits.append(
                SemanticHit(
                    path=str(row["path"]),
                    start_line=int(row["start_line"]),
                    end_line=int(row["end_line"]),
                    score=score,
                    rank=len(hits) + 1,
                    symbol=str(row["symbol"]) if row["symbol"] else None,
                )
            )
        return hits

    def _query_exact(
        self,
        conn: sqlite3.Connection,
        query_vector: list[float],
        *,
        top_k: int,
        min_score: float,
    ) -> list[SemanticHit]:
        """Return deterministic exact-cosine hits for one query vector."""
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in conn.execute(
            """
            SELECT path, start_line, end_line, symbol, vector_json
            FROM chunks
            """
        ):
            vector = [float(value) for value in json.loads(row["vector_json"])]
            score = _cosine(query_vector, vector)
            if score >= min_score:
                scored.append((score, row))
        scored.sort(
            key=lambda pair: (
                -pair[0],
                str(pair[1]["path"]),
                int(pair[1]["start_line"]),
            )
        )
        return [
            SemanticHit(
                path=str(row["path"]),
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                score=float(score),
                rank=rank,
                symbol=str(row["symbol"]) if row["symbol"] else None,
            )
            for rank, (score, row) in enumerate(scored[:top_k], start=1)
        ]

    def _query_single(
        self,
        conn: sqlite3.Connection,
        query_vector: list[float],
        *,
        top_k: int,
        min_score: float,
    ) -> list[SemanticHit]:
        """Return ANN or exact-cosine hits for one semantic query view."""
        ann_hits = self._query_ann(
            conn,
            query_vector,
            top_k=top_k,
            min_score=min_score,
        )
        if ann_hits is not None:
            return ann_hits
        return self._query_exact(
            conn,
            query_vector,
            top_k=top_k,
            min_score=min_score,
        )

    def query(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> list[SemanticHit]:
        """Return top chunk hits after synchronizing changed repository evidence."""
        if top_k <= 0:
            raise ValueError("semantic top_k must be positive")
        if not -1.0 <= min_score <= 1.0:
            raise ValueError("semantic min_score must be between -1 and 1")
        views = _semantic_query_views(query)
        if not views:
            return []
        self.sync()
        conn = _connect(self.path)
        try:
            per_view_hits: list[list[SemanticHit]] = []
            for view in views:
                query_vector = self._query_vector(conn, view)
                per_view_hits.append(
                    self._query_single(
                        conn,
                        query_vector,
                        top_k=top_k,
                        min_score=min_score,
                    )
                )
            return _fuse_query_view_hits(
                per_view_hits,
                top_k=top_k,
            )
        finally:
            conn.close()

    def status(self, *, conn: sqlite3.Connection | None = None) -> SemanticIndexStats:
        """Return persistent semantic-index counts without loading source text."""
        owns = conn is None
        connection = conn or _connect(self.path)
        try:
            meta = _meta(connection)
            files = int(
                connection.execute(
                    "SELECT COUNT(*) AS n FROM files"
                ).fetchone()["n"]
            )
            chunks = int(
                connection.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            )
            return SemanticIndexStats(
                files=files,
                chunks=chunks,
                dimensions=int(meta.get("dimensions", "0")),
                model=meta.get("model", self.model),
                model_revision=meta.get("model_revision") or self.model_revision,
                backend=_effective_backend(self.path, meta),
                path=str(self.path),
            )
        finally:
            if owns:
                connection.close()


def semantic_status(root: Path, model: str = DEFAULT_MODEL) -> dict:
    """Return semantic index status without requiring the embedding dependency."""
    revision = _model_revision()
    path = semantic_index_path(root.resolve(), model, revision)
    if not path.is_file():
        return SemanticIndexStats(
            files=0,
            chunks=0,
            dimensions=0,
            model=model,
            model_revision=revision,
            backend="sqlite-cosine",
            path=str(path),
        ).to_dict()
    conn = _connect(path)
    try:
        meta = _meta(conn)
        files = int(
            conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        )
        chunks = int(conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"])
        return SemanticIndexStats(
            files=files,
            chunks=chunks,
            dimensions=int(meta.get("dimensions", "0")),
            model=meta.get("model", model),
            model_revision=meta.get("model_revision") or revision,
            backend=_effective_backend(path, meta),
            path=str(path),
        ).to_dict()
    finally:
        conn.close()

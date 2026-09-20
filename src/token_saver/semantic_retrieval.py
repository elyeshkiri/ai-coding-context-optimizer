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
from pathlib import Path
import sqlite3
from typing import Protocol

from .repo_index import RepositoryIndex
from .state import state_dir

SEMANTIC_SCHEMA = 1
DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_CHUNK_LINES = 64
DEFAULT_CHUNK_OVERLAP = 12
DEFAULT_TOP_K = 40
DEFAULT_MIN_SCORE = 0.12
MAX_EMBED_CHARS = 12000


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
            "backend": self.backend,
            "path": self.path,
        }


def _project_id(root: Path) -> str:
    """Return an opaque stable project identifier."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def _model_id(model: str) -> str:
    """Return a filesystem-safe model identity."""
    return hashlib.sha256(model.encode()).hexdigest()[:16]


def semantic_index_path(root: Path, model: str = DEFAULT_MODEL) -> Path:
    """Return the private SQLite semantic-index path."""
    return (
        state_dir()
        / "semantic-index"
        / _project_id(root)
        / f"{_model_id(model)}.sqlite3"
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
        return SentenceTransformer(model, local_files_only=True)
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


def _chunk_source(
    rel: str,
    text: str,
    record,
    *,
    chunk_lines: int,
    overlap: int,
) -> list[tuple[int, int, str, str | None]]:
    """Create deterministic overlapping source chunks with semantic prefixes."""
    if chunk_lines <= 0:
        raise ValueError("semantic chunk_lines must be positive")
    if overlap < 0 or overlap >= chunk_lines:
        raise ValueError("semantic overlap must satisfy 0 <= overlap < chunk_lines")
    lines = text.splitlines()
    if not lines:
        return []
    step = chunk_lines - overlap
    chunks: list[tuple[int, int, str, str | None]] = []
    for offset in range(0, len(lines), step):
        start = offset + 1
        end = min(len(lines), offset + chunk_lines)
        symbol = _symbol_for_range(record, start, end)
        prefix = f"path: {rel}\n"
        if symbol:
            prefix += f"symbol: {symbol}\n"
        body = "\n".join(lines[offset:end])
        rendered = (prefix + body)[:MAX_EMBED_CHARS]
        chunks.append((start, end, rendered, symbol))
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
        self.chunk_lines = chunk_lines
        self.overlap = overlap
        self._encoder = encoder
        self.path = semantic_index_path(self.root, model)

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
            "chunk_lines": str(self.chunk_lines),
            "overlap": str(self.overlap),
        }
        current = _meta(conn)
        if current and any(current.get(key) != value for key, value in expected.items()):
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
                    "SELECT path, MIN(file_digest) AS file_digest FROM chunks GROUP BY path"
                )
            }
            stale_paths = sorted(set(existing) - current_paths)
            for stale in stale_paths:
                conn.execute("DELETE FROM chunks WHERE path = ?", (stale,))

            pending: list[tuple[str, str, int, int, str | None, str]] = []
            changed_paths: list[str] = []
            for rel, record in sorted(self.index.records.items()):
                if existing.get(rel) == record.digest:
                    continue
                changed_paths.append(rel)
                path = self.root / rel
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for start, end, body, symbol in _chunk_source(
                    rel,
                    text,
                    record,
                    chunk_lines=self.chunk_lines,
                    overlap=self.overlap,
                ):
                    chunk_id = hashlib.sha256(
                        f"{rel}\0{record.digest}\0{start}\0{end}".encode()
                    ).hexdigest()
                    pending.append(
                        (chunk_id, rel, record.digest, start, end, symbol, body)
                    )

            vectors = _encode(
                self._get_encoder(),
                [item[-1] for item in pending],
            )
            if pending and len(vectors) != len(pending):
                raise RuntimeError("embedding encoder returned the wrong batch size")
            dimensions = len(vectors[0]) if vectors else int(_meta(conn).get("dimensions", "0"))
            if vectors and any(len(vector) != dimensions for vector in vectors):
                raise RuntimeError("embedding encoder returned inconsistent dimensions")

            for rel in changed_paths:
                conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
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
        key = hashlib.sha256(f"{self.model}\0{digest}".encode()).hexdigest()
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
        self.sync()
        conn = _connect(self.path)
        try:
            query_vector = self._query_vector(conn, query)
            ann_hits = self._query_ann(
                conn,
                query_vector,
                top_k=top_k,
                min_score=min_score,
            )
            if ann_hits is not None:
                return ann_hits
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
                    "SELECT COUNT(DISTINCT path) AS n FROM chunks"
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
                backend=meta.get("ann_backend", "sqlite-cosine"),
                path=str(self.path),
            )
        finally:
            if owns:
                connection.close()


def semantic_status(root: Path, model: str = DEFAULT_MODEL) -> dict:
    """Return semantic index status without requiring the embedding dependency."""
    path = semantic_index_path(root.resolve(), model)
    if not path.is_file():
        return SemanticIndexStats(
            files=0,
            chunks=0,
            dimensions=0,
            model=model,
            backend=meta.get("ann_backend", "sqlite-cosine"),
            path=str(path),
        ).to_dict()
    conn = _connect(path)
    try:
        meta = _meta(conn)
        files = int(
            conn.execute("SELECT COUNT(DISTINCT path) AS n FROM chunks").fetchone()["n"]
        )
        chunks = int(conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"])
        return SemanticIndexStats(
            files=files,
            chunks=chunks,
            dimensions=int(meta.get("dimensions", "0")),
            model=meta.get("model", model),
            backend="sqlite-cosine",
            path=str(path),
        ).to_dict()
    finally:
        conn.close()

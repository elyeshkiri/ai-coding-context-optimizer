"""Content-addressed exact-byte recovery for lossy Token Saver transforms."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from .state import state_dir

DEFAULT_CAPACITY_BYTES = 512 * 1024 * 1024
_HANDLE_PREFIX = "tsr_"


class RecoveryCapacityError(RuntimeError):
    """Raised when adding a payload would exceed the configured recovery cap."""


@dataclass(frozen=True)
class RecoveryRecord:
    """Metadata plus exact recovered bytes for one content-addressed payload."""

    handle: str
    content_type: str
    payload: bytes
    metadata: dict
    created_at: int
    last_accessed_at: int | None
    access_count: int

    @property
    def size_bytes(self) -> int:
        """Return exact payload size."""
        return len(self.payload)


def _project_id(root: Path) -> str:
    """Return an opaque stable identifier for one project root."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def recovery_path(root: Path) -> Path:
    """Return the private project-scoped recovery database path."""
    return state_dir() / "recovery" / f"{_project_id(root)}.sqlite3"


def recovery_handle(payload: bytes) -> str:
    """Return a deterministic content-addressed handle for exact bytes."""
    digest = hashlib.sha256(payload).hexdigest()
    return _HANDLE_PREFIX + digest[:32]


class RecoveryStore:
    """Persist exact bytes before a lossy transform and recover them by handle."""

    def __init__(
        self,
        root: Path,
        *,
        capacity_bytes: int = DEFAULT_CAPACITY_BYTES,
    ):
        """Create one project-scoped recovery store."""
        if capacity_bytes <= 0:
            raise ValueError("recovery capacity_bytes must be positive")
        self.root = root.resolve()
        self.path = recovery_path(self.root)
        self.capacity_bytes = int(capacity_bytes)

    def _connect(self) -> sqlite3.Connection:
        """Open and initialize the private SQLite store."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS recovery (
                handle TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                content_type TEXT NOT NULL,
                payload BLOB NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_accessed_at INTEGER,
                access_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return connection

    def put(
        self,
        payload: bytes | str,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> str:
        """Store exact bytes before transformation without evicting older records."""
        raw = payload.encode() if isinstance(payload, str) else bytes(payload)
        handle = recovery_handle(raw)
        digest = hashlib.sha256(raw).hexdigest()
        encoded_metadata = json.dumps(
            metadata or {},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        now = int(time.time())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM recovery WHERE handle = ?",
                (handle,),
            ).fetchone()
            if existing:
                return handle
            used = connection.execute(
                "SELECT COALESCE(SUM(length(payload)), 0) FROM recovery"
            ).fetchone()[0]
            if int(used or 0) + len(raw) > self.capacity_bytes:
                raise RecoveryCapacityError(
                    "recovery capacity exceeded; original payload was not transformed"
                )
            connection.execute(
                """
                INSERT INTO recovery (
                    handle, digest, content_type, payload, metadata_json,
                    created_at, last_accessed_at, access_count
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                (
                    handle,
                    digest,
                    content_type,
                    sqlite3.Binary(raw),
                    encoded_metadata,
                    now,
                ),
            )
            connection.commit()
        return handle

    def get(self, handle: str) -> RecoveryRecord:
        """Return exact stored bytes and record bounded access telemetry."""
        if not isinstance(handle, str) or not handle.startswith(_HANDLE_PREFIX):
            raise ValueError("invalid recovery handle")
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT handle, content_type, payload, metadata_json, created_at,
                       last_accessed_at, access_count, digest
                FROM recovery WHERE handle = ?
                """,
                (handle,),
            ).fetchone()
            if row is None:
                raise KeyError(handle)
            payload = bytes(row[2])
            if hashlib.sha256(payload).hexdigest() != row[7]:
                raise RuntimeError("recovery payload integrity check failed")
            count = int(row[6] or 0) + 1
            connection.execute(
                """
                UPDATE recovery
                SET last_accessed_at = ?, access_count = ?
                WHERE handle = ?
                """,
                (now, count, handle),
            )
            connection.commit()
        metadata = json.loads(row[3])
        if not isinstance(metadata, dict):
            metadata = {}
        return RecoveryRecord(
            handle=row[0],
            content_type=row[1],
            payload=payload,
            metadata=metadata,
            created_at=int(row[4]),
            last_accessed_at=now,
            access_count=count,
        )

    def info(self, handle: str) -> dict:
        """Return metadata without returning payload bytes."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT handle, content_type, length(payload), metadata_json,
                       created_at, last_accessed_at, access_count
                FROM recovery WHERE handle = ?
                """,
                (handle,),
            ).fetchone()
        if row is None:
            raise KeyError(handle)
        metadata = json.loads(row[3])
        return {
            "handle": row[0],
            "content_type": row[1],
            "size_bytes": int(row[2]),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": int(row[4]),
            "last_accessed_at": row[5],
            "access_count": int(row[6] or 0),
        }

    def stats(self) -> dict:
        """Return capacity and record counts without exposing recovered content."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(length(payload)), 0)
                FROM recovery
                """
            ).fetchone()
        used = int(row[1] or 0)
        return {
            "path": str(self.path),
            "records": int(row[0] or 0),
            "used_bytes": used,
            "capacity_bytes": self.capacity_bytes,
            "remaining_bytes": max(0, self.capacity_bytes - used),
        }

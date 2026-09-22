"""Private project-scoped persistence for session-efficiency evidence."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from ..state import state_dir

SCHEMA = 1
MAX_EVENT_BYTES = 2_000_000
KEEP_EVENTS = 4000


def _project_id(root: Path) -> str:
    """Return a stable opaque identifier for one repository path."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def directory() -> Path:
    """Return the private efficiency-state directory."""
    return state_dir() / "efficiency"


def snapshot_path(root: Path) -> Path:
    """Return the structured continuity snapshot path for one project."""
    return directory() / f"{_project_id(root)}.json"


def events_path(root: Path) -> Path:
    """Return the append-only efficiency-event path for one project."""
    return directory() / f"{_project_id(root)}.jsonl"


@contextmanager
def _locked(path: Path):
    """Hold an exclusive cross-platform lock for one state path."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomically write a private JSON snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_snapshot(root: Path) -> dict:
    """Load one project snapshot, returning an initialized structure on failure."""
    path = snapshot_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema", SCHEMA)
    payload.setdefault("sessions", {})
    payload.setdefault("last_session", None)
    return payload


def update_snapshot(root: Path, mutate) -> dict:
    """Mutate one project snapshot under a lock and return the saved value."""
    path = snapshot_path(root)
    with _locked(path):
        payload = load_snapshot(root)
        mutate(payload)
        payload["schema"] = SCHEMA
        payload["updated_at"] = int(time.time())
        _atomic_write(path, payload)
        return payload


def append_event(root: Path, event: dict) -> None:
    """Append one bounded content-free efficiency event."""
    path = events_path(root)
    record = {
        "schema": SCHEMA,
        "recorded_at": int(time.time()),
        **event,
    }
    with _locked(path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = path.exists()
        with path.open("a", encoding="utf-8") as handle:
            json.dump(record, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not existed:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _compact_events(path)


def _compact_events(path: Path) -> None:
    """Bound a large event ledger while preserving the newest complete rows."""
    try:
        if path.stat().st_size <= MAX_EVENT_BYTES:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    kept = lines[-KEEP_EVENTS:]
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if kept:
                handle.write("\n".join(kept) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_events(root: Path, *, since: int | None = None) -> list[dict]:
    """Load valid efficiency events, optionally filtering by Unix timestamp."""
    path = events_path(root)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records: list[dict] = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("schema") != SCHEMA:
            continue
        recorded = item.get("recorded_at")
        if since is not None and (
            not isinstance(recorded, int) or recorded < since
        ):
            continue
        records.append(item)
    return records

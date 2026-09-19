"""Session-scoped JSON ledger with locked transactions and atomic writes."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = 3

def state_dir() -> Path:
    return Path(os.environ.get("TOKEN_SAVER_STATE_DIR", str(Path.home() / ".claude" / "token-saver")))

def state_path(root: Path | None = None, session_id: str | None = None) -> Path:
    identity = str(root.resolve()) if root else "global"
    if session_id:
        identity += "\0" + session_id
    return state_dir() / (hashlib.sha256(identity.encode()).hexdigest() + ".json")

def load(root: Path | None = None, session_id: str | None = None) -> dict:
    try:
        data = json.loads(state_path(root, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key, default in (
        ("schema", SCHEMA), ("reads", {}), ("usage", {}), ("advice", []),
        ("diagnostics", {}),
    ):
        data.setdefault(key, default)
    return data

@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0); handle.write(b"0"); handle.flush(); handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)

def _write(data: dict, path: Path) -> Path:
    data = dict(data, schema=SCHEMA, updated=int(time.time()))
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    return path

def save(data: dict, root: Path | None = None, session_id: str | None = None) -> Path:
    path = state_path(root, session_id)
    with _locked(path):
        return _write(data, path)

def update(root: Path | None, mutate, session_id: str | None = None) -> Path:
    path = state_path(root, session_id)
    with _locked(path):
        data = load(root, session_id)
        mutate(data)
        return _write(data, path)

def record_read(root: Path, path: Path, digest: str, session_id: str | None = None) -> None:
    def mutate(data):
        reads = data.setdefault("reads", {})
        reads[str((root / path).resolve())] = digest
        if len(reads) > 400:
            for key in list(reads)[:-300]: reads.pop(key, None)
    update(root, mutate, session_id)

def seen_read(root: Path, path: Path, digest: str, session_id: str | None = None) -> bool:
    return load(root, session_id)["reads"].get(str((root / path).resolve())) == digest

def record_usage(root: Path, usage: dict, session_id: str | None = None) -> None:
    def mutate(data):
        bucket = data.setdefault("usage", {})
        for key, value in usage.items():
            try: bucket[key] = int(bucket.get(key, 0)) + int(value or 0)
            except (TypeError, ValueError): continue
        bucket["turns"] = int(bucket.get("turns", 0)) + 1
    update(root, mutate, session_id)

def diagnostic_snapshot(
    root: Path, command_key: str, session_id: str | None = None,
) -> dict | None:
    value = load(root, session_id).get("diagnostics", {}).get(command_key)
    return value if isinstance(value, dict) else None


def record_diagnostic_snapshot(
    root: Path, command_key: str, snapshot: dict,
    session_id: str | None = None,
) -> None:
    def mutate(data):
        diagnostics = data.setdefault("diagnostics", {})
        diagnostics.pop(command_key, None)
        diagnostics[command_key] = snapshot
        if len(diagnostics) > 30:
            for key in list(diagnostics)[:-24]:
                diagnostics.pop(key, None)
    update(root, mutate, session_id)


def reset_session(root: Path, *, reads: bool = True, reminder: bool = True, session_id: str | None = None) -> None:
    def mutate(data):
        if reads: data.update(reads={}, usage={}, diagnostics={})
        if reminder: data["reminder"] = ""
    update(root, mutate, session_id)

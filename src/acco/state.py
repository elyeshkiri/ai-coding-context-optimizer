"""Session-scoped JSON ledger with locked transactions and atomic writes."""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
import json
import os
import tempfile
import time
from pathlib import Path

from .file_lock import locked_file

SCHEMA = 3

def _default_state_dir(
    *,
    platform_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the platform-native private ACCO state directory."""
    platform_name = platform_name or os.name
    environment = os.environ if environ is None else environ
    if platform_name == "nt":
        local = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        if local:
            return Path(local) / "ACCO"
    return (home or Path.home()) / ".claude" / "acco"


def state_dir() -> Path:
    """Return ACCO state storage, honoring the explicit environment override."""
    override = os.environ.get("ACCO_STATE_DIR")
    return Path(override).expanduser() if override else _default_state_dir()

def state_path(root: Path | None = None, session_id: str | None = None) -> Path:
    """Handle state path."""
    identity = str(root.resolve()) if root else "global"
    if session_id:
        identity += "\0" + session_id
    return state_dir() / (hashlib.sha256(identity.encode()).hexdigest() + ".json")

def load(root: Path | None = None, session_id: str | None = None) -> dict:
    """Load the requested value."""
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
    """Compatibility lock seam used by state and validated config writes."""
    with locked_file(Path(str(path) + ".lock")):
        yield


def _write(data: dict, path: Path) -> Path:
    """Write the requested value."""
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
    """Save the requested value."""
    path = state_path(root, session_id)
    with _locked(path):
        return _write(data, path)

def update(root: Path | None, mutate, session_id: str | None = None) -> Path:
    """Update the requested value."""
    path = state_path(root, session_id)
    with _locked(path):
        data = load(root, session_id)
        mutate(data)
        return _write(data, path)

def record_read(root: Path, path: Path, digest: str, session_id: str | None = None) -> None:
    """Record read."""
    def mutate(data):
        reads = data.setdefault("reads", {})
        reads[str((root / path).resolve())] = digest
        if len(reads) > 400:
            for key in list(reads)[:-300]: reads.pop(key, None)
    update(root, mutate, session_id)

def seen_read(root: Path, path: Path, digest: str, session_id: str | None = None) -> bool:
    """Return whether seen read."""
    return load(root, session_id)["reads"].get(str((root / path).resolve())) == digest

def record_usage(root: Path, usage: dict, session_id: str | None = None) -> None:
    """Record usage."""
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
    """Handle diagnostic snapshot."""
    value = load(root, session_id).get("diagnostics", {}).get(command_key)
    return value if isinstance(value, dict) else None


def record_diagnostic_snapshot(
    root: Path, command_key: str, snapshot: dict,
    session_id: str | None = None,
) -> None:
    """Record diagnostic snapshot."""
    def mutate(data):
        diagnostics = data.setdefault("diagnostics", {})
        diagnostics.pop(command_key, None)
        diagnostics[command_key] = snapshot
        if len(diagnostics) > 30:
            for key in list(diagnostics)[:-24]:
                diagnostics.pop(key, None)
    update(root, mutate, session_id)


def reset_session(root: Path, *, reads: bool = True, reminder: bool = True, session_id: str | None = None) -> None:
    """Reset session."""
    def mutate(data):
        if reads:
            data.update(
                reads={},
                usage={},
                diagnostics={},
                output_policy={},
                model_route={},
            )
        data.pop("output_telemetry_pending", None)
        if reminder:
            data["reminder"] = ""
    update(root, mutate, session_id)

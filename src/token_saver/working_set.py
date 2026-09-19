"""Small, explicit task-session memory for context-pack continuity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def _path(root: Path, session: str) -> Path:
    """Handle path."""
    configured = os.environ.get("TOKEN_SAVER_STATE_DIR")
    base = Path(configured).expanduser() if configured else Path.home() / ".claude" / "token-saver"
    key = hashlib.sha256(f"{root.resolve()}\0{session}".encode()).hexdigest()[:20]
    return base / "working-sets" / f"{key}.json"


def load_working_set(root: Path, session: str) -> tuple[set[str], set[str]]:
    """Load working set."""
    try:
        payload = json.loads(_path(root, session).read_text(encoding="utf-8"))
        return set(payload.get("files", [])), set(payload.get("terms", []))
    except (OSError, ValueError, TypeError):
        return set(), set()


def save_working_set(root: Path, session: str, query: str, files: list[str]) -> None:
    """Save working set."""
    target = _path(root, session)
    target.parent.mkdir(parents=True, exist_ok=True)
    terms = sorted(set(re.findall(r"[A-Za-z0-9_$]{2,}", query.lower())))
    payload = {"files": files, "terms": terms}
    fd, tmp_name = tempfile.mkstemp(prefix=target.name, dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        os.replace(tmp_name, target)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass

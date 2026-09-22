"""Inspectable, project-local ranking feedback with atomic persistence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def _path(root: Path) -> Path:
    """Handle path."""
    state = os.environ.get("ACCO_STATE_DIR")
    base = Path(state).expanduser() if state else Path.home() / ".claude" / "acco"
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return base / "feedback" / f"{key}.json"


def load_feedback(root: Path) -> dict[str, int]:
    """Load feedback."""
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return {str(path): int(score) for path, score in data.get("files", {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def record_feedback(root: Path, path: str, *, useful: bool) -> dict[str, int]:
    """Record feedback."""
    target = _path(root)
    scores = load_feedback(root)
    normalized = path.replace("\\", "/").lstrip("./")
    scores[normalized] = max(-10, min(10, scores.get(normalized, 0) + (1 if useful else -1)))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name, dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "files": scores}, handle, sort_keys=True)
        os.replace(tmp, target)
    finally:
        try:
            Path(tmp).unlink()
        except FileNotFoundError:
            pass
    return scores


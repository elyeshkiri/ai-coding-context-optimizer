"""Detect a stale CODEMAP so a drifted index does not cost extra turns."""

from __future__ import annotations

from pathlib import Path

from .skeleton import walk_repo


def map_freshness(root: Path, map_path: Path | None = None) -> tuple[bool, str]:
    """Return (fresh, reason). Missing map is not an error — it is optional."""
    root = root.resolve()
    target = map_path or (root / "CODEMAP.md")
    if not target.is_file():
        return True, "no CODEMAP.md (maps are optional)"
    map_mtime = target.stat().st_mtime
    newest: Path | None = None
    newest_mtime = map_mtime
    for path in walk_repo(root):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = path
    if newest is None:
        return True, "CODEMAP.md is newer than tracked sources"
    rel = newest.relative_to(root).as_posix()
    return False, (
        f"CODEMAP.md older than {rel} — "
        "token-saver map . --max-tokens 8000 -o CODEMAP.md --refresh-if-stale"
    )

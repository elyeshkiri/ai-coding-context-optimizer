"""Fast persistent repository-index refresh for query-time retrieval.

`repo_index.build_index` remains the authoritative full/content-digest builder.
This module adds a stat sidecar for warm query paths: after the first full build,
unchanged files are reused from the persisted index using `(size, mtime_ns)` and
are not opened at all. Only files whose metadata changed are reread/reparsed.

The sidecar is an optimization, never the source of truth: deleting it forces a
full digest-backed rebuild. This keeps the conservative builder available for
explicit validation while removing O(repository source bytes) I/O from normal
warm packing queries.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .repo_index import (
    RepositoryIndex,
    _default_cache,
    _load,
    _save,
    _semantic_requested,
    build_index as build_full_index,
    record_for_text,
)
from .security import inspect_path
from .skeleton import walk_repo

_META_VERSION = 1


def _meta_path(index_path: Path) -> Path:
    return index_path.with_name(index_path.name + ".stat.json")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_meta(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != _META_VERSION:
        return None
    files = payload.get("files")
    if not isinstance(files, dict):
        return None
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _stat_entry(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _snapshot_stats(
    root: Path,
    *,
    use_gitignore: bool,
    index_path: Path,
    meta_path: Path,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    files: dict[str, dict[str, int]] = {}
    excluded: dict[str, str] = {}
    resolved_index = index_path.resolve() if index_path.exists() else index_path.absolute()
    resolved_meta = meta_path.resolve() if meta_path.exists() else meta_path.absolute()
    for path in walk_repo(root, use_gitignore=use_gitignore):
        absolute = path.resolve()
        if absolute in {resolved_index, resolved_meta}:
            continue
        decision = inspect_path(root, path)
        if not decision.allowed:
            try:
                excluded[path.relative_to(root).as_posix()] = decision.reason
            except ValueError:
                excluded[str(path)] = decision.reason
            continue
        entry = _stat_entry(path)
        if entry is None:
            continue
        files[path.relative_to(root).as_posix()] = entry
    return files, excluded


def _apply_semantic(
    root: Path,
    records: dict,
    *,
    enabled: bool,
    strict: bool,
) -> None:
    if enabled:
        from .semantic_ts import resolve_typescript_edges
        semantic = resolve_typescript_edges(root, strict=strict)
        for rel, record in records.items():
            record.semantic_refs = [
                target for target in semantic.get(rel, [])
                if target in records and target != rel
            ]
    else:
        for record in records.values():
            record.semantic_refs = []


def build_query_index(
    root: Path,
    *,
    use_gitignore: bool = True,
    cache_path: Path | None = None,
    persist: bool = True,
    typescript_semantic: bool | None = None,
    strict_semantic: bool = False,
) -> RepositoryIndex:
    """Build/refresh an index without reopening unchanged source files.

    `persist=False` deliberately uses the full builder because there is no
    durable metadata to trust across calls.
    """
    root = root.resolve()
    if not persist:
        return build_full_index(
            root,
            use_gitignore=use_gitignore,
            cache_path=cache_path,
            persist=False,
            typescript_semantic=typescript_semantic,
            strict_semantic=strict_semantic,
        )

    target = cache_path or _default_cache(root)
    meta_target = _meta_path(target)
    old = _load(target)
    meta = _load_meta(meta_target)
    semantic_enabled = _semantic_requested(typescript_semantic)

    # No trustworthy stat sidecar: do one conservative digest-backed build,
    # then record metadata so every following warm query can be read-free.
    if not old or meta is None:
        index = build_full_index(
            root,
            use_gitignore=use_gitignore,
            cache_path=target,
            persist=True,
            typescript_semantic=typescript_semantic,
            strict_semantic=strict_semantic,
        )
        stats, _ = _snapshot_stats(
            root, use_gitignore=use_gitignore, index_path=target, meta_path=meta_target
        )
        _write_json_atomic(meta_target, {
            "version": _META_VERSION,
            "semantic_enabled": semantic_enabled,
            "files": stats,
        })
        return index

    current_stats, excluded = _snapshot_stats(
        root, use_gitignore=use_gitignore, index_path=target, meta_path=meta_target
    )
    old_stats = meta.get("files", {})
    records = {}
    reparsed = reused = 0
    changed = False

    for rel, stat in current_stats.items():
        prior = old.get(rel)
        prior_stat = old_stats.get(rel) if isinstance(old_stats, dict) else None
        if prior is not None and prior_stat == stat:
            records[rel] = prior
            reused += 1
            continue
        try:
            text = _read_text(root / rel)
        except OSError:
            continue
        records[rel] = record_for_text(rel, text)
        reparsed += 1
        changed = True

    if set(old) != set(records):
        changed = True

    previous_semantic = bool(meta.get("semantic_enabled", False))
    semantic_needs_refresh = semantic_enabled and (changed or not previous_semantic)
    semantic_needs_clear = (not semantic_enabled) and previous_semantic
    if semantic_needs_refresh:
        _apply_semantic(root, records, enabled=True, strict=strict_semantic)
        changed = True
    elif semantic_needs_clear:
        _apply_semantic(root, records, enabled=False, strict=strict_semantic)
        changed = True

    if changed:
        _save(target, records)
    # Refreshing the sidecar is cheap and also records deletions/additions.
    _write_json_atomic(meta_target, {
        "version": _META_VERSION,
        "semantic_enabled": semantic_enabled,
        "files": current_stats,
    })
    return RepositoryIndex(
        root, records, reparsed, reused, excluded, semantic_enabled
    )

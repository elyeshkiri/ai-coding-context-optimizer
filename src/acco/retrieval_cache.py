"""Persistent content-fingerprinted cache for completed context packs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from .feedback import load_feedback
from .packing.contracts import ContextPack, RankedFile
from .repo_index import INDEX_VERSION, RepositoryIndex
from .state import state_dir
from .working_set import load_working_set

CACHE_SCHEMA = 1


def repository_fingerprint(index: RepositoryIndex) -> str:
    """Hash retrieval-relevant repository evidence, not just mtimes."""
    rows = []
    for rel, record in sorted(index.records.items()):
        rows.append(
            (
                rel,
                record.digest,
                record.semantic_refs or [],
            )
        )
    payload = json.dumps(
        {"index_version": INDEX_VERSION, "records": rows},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _project_id(root: Path) -> str:
    """Return an opaque stable project cache namespace."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]


def _directory(root: Path) -> Path:
    """Return the private retrieval-cache directory."""
    return state_dir() / "retrieval-cache" / _project_id(root)


def _stable_set(value: set[str] | None) -> list[str] | None:
    """Normalize an optional set for deterministic key material."""
    return sorted(value) if value is not None else None


def cache_key(
    root: Path,
    index: RepositoryIndex,
    *,
    query: str,
    max_tokens: int,
    max_files: int,
    context_lines: int,
    use_gitignore: bool,
    changed_boost: bool,
    graph_hops: int,
    duplicate_threshold: float,
    session: str | None,
    embeddings: bool,
    target_symbol: str | None,
    feedback_boost: bool,
    closure_max_items: int,
    changed_files: set[str] | None,
    priority_files: set[str] | None,
    exclude_files: set[str] | None,
    restrict_files: set[str] | None,
    adaptive_budget: bool,
) -> str:
    """Build a cache key from content identity plus retrieval configuration."""
    working_files: list[str] = []
    working_terms: list[str] = []
    if session:
        files, terms = load_working_set(root, session)
        working_files, working_terms = sorted(files), sorted(terms)
    feedback = (
        sorted(load_feedback(root).items())
        if feedback_boost
        else []
    )
    payload = {
        "schema": CACHE_SCHEMA,
        "repository": repository_fingerprint(index),
        "query": query,
        "max_tokens": max_tokens,
        "max_files": max_files,
        "context_lines": context_lines,
        "use_gitignore": use_gitignore,
        "changed_boost": changed_boost,
        "graph_hops": graph_hops,
        "duplicate_threshold": duplicate_threshold,
        "session": session,
        "working_files": working_files,
        "working_terms": working_terms,
        "embeddings": embeddings,
        "target_symbol": target_symbol,
        "feedback_boost": feedback_boost,
        "feedback": feedback,
        "closure_max_items": closure_max_items,
        "changed_files": _stable_set(changed_files),
        "priority_files": _stable_set(priority_files),
        "exclude_files": _stable_set(exclude_files),
        "restrict_files": _stable_set(restrict_files),
        "adaptive_budget": adaptive_budget,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _ranked_to_dict(item: RankedFile) -> dict:
    """Serialize ranking evidence without duplicating source-file contents."""
    return {
        "rel": item.rel,
        "outline": item.outline,
        "score": item.score,
        "reasons": list(item.reasons),
        "term_hits": item.term_hits,
        "changed": item.changed,
    }


def _pack_to_dict(pack: ContextPack) -> dict:
    """Serialize the stable public context-pack result."""
    return {
        "text": pack.text,
        "estimated_tokens": pack.estimated_tokens,
        "scanned_files": pack.scanned_files,
        "selected_files": pack.selected_files,
        "ranked": [_ranked_to_dict(item) for item in pack.ranked],
        "selected_symbols": pack.selected_symbols,
        "selected_symbol_identities": pack.selected_symbol_identities,
        "redactions": pack.redactions,
        "closure_files": pack.closure_files,
        "retrieval_plan": pack.retrieval_plan,
    }


def _pack_from_dict(root: Path, payload: dict, key: str) -> ContextPack:
    """Reconstruct a context pack while leaving large source text uncached."""
    ranked = []
    for raw in payload.get("ranked", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("rel"), str):
            continue
        rel = raw["rel"]
        ranked.append(
            RankedFile(
                path=root / rel,
                rel=rel,
                text="",
                outline=str(raw.get("outline", "")),
                score=float(raw.get("score", 0.0)),
                reasons=[str(value) for value in raw.get("reasons", [])],
                term_hits=int(raw.get("term_hits", 0)),
                changed=bool(raw.get("changed", False)),
            )
        )
    return ContextPack(
        text=str(payload["text"]),
        estimated_tokens=int(payload["estimated_tokens"]),
        scanned_files=int(payload["scanned_files"]),
        selected_files=[str(value) for value in payload.get("selected_files", [])],
        ranked=ranked,
        selected_symbols=[str(value) for value in payload.get("selected_symbols", [])],
        selected_symbol_identities=[
            str(value) for value in payload.get("selected_symbol_identities", [])
        ],
        redactions=[str(value) for value in payload.get("redactions", [])],
        closure_files=[str(value) for value in payload.get("closure_files", [])],
        retrieval_plan={
            str(name): int(value)
            for name, value in payload.get("retrieval_plan", {}).items()
        },
        cache_hit=True,
        cache_key=key,
    )


def load(root: Path, key: str) -> ContextPack | None:
    """Load a cache entry if its payload is intact."""
    path = _directory(root) / f"{key}.json"
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(wrapper, dict)
        or wrapper.get("schema") != CACHE_SCHEMA
        or wrapper.get("key") != key
        or not isinstance(wrapper.get("pack"), dict)
    ):
        return None
    try:
        pack = _pack_from_dict(root.resolve(), wrapper["pack"], key)
    except (KeyError, TypeError, ValueError):
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return pack


def store(
    root: Path,
    key: str,
    pack: ContextPack,
    *,
    max_entries: int = 64,
) -> None:
    """Atomically persist one completed pack and prune oldest entries."""
    if max_entries < 1:
        raise ValueError("retrieval cache max_entries must be positive")
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{key}.json"
    wrapper = {
        "schema": CACHE_SCHEMA,
        "key": key,
        "created_at": int(time.time()),
        "pack": _pack_to_dict(pack),
    }
    fd, temporary = tempfile.mkstemp(
        dir=directory,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(wrapper, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass

    entries = sorted(
        directory.glob("*.json"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    for old in entries[max_entries:]:
        try:
            old.unlink()
        except OSError:
            pass


def status(root: Path) -> dict:
    """Return cache entry count and private local storage path."""
    directory = _directory(root)
    entries = list(directory.glob("*.json")) if directory.is_dir() else []
    return {
        "schema": CACHE_SCHEMA,
        "entries": len(entries),
        "path": str(directory),
    }

"""Durable evidence-backed project knowledge for cross-session reuse."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from .state import state_dir

SCHEMA = 1
MAX_FINDINGS = 500
MAX_ANCHORS = 8
MAX_INVALIDATORS = 8
CONFIDENCE = {"speculative", "probable", "verified"}
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\\-]{1,}")


def _project_id(root: Path) -> str:
    """Return a stable opaque identifier for one repository path."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def knowledge_path(root: Path) -> Path:
    """Return the private durable-knowledge file for one repository."""
    return state_dir() / "knowledge" / f"{_project_id(root)}.json"


@contextmanager
def _locked(path: Path):
    """Hold an exclusive cross-platform lock for one knowledge file."""
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
    """Atomically write one private knowledge snapshot."""
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


def _load(root: Path) -> dict:
    """Load a knowledge snapshot and normalize malformed state conservatively."""
    path = knowledge_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    findings = payload.get("findings")
    payload["findings"] = findings if isinstance(findings, list) else []
    payload["schema"] = SCHEMA
    return payload


def _file_digest(path: Path) -> str | None:
    """Return a content digest for one file or None when unavailable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _normalize_anchor(root: Path, value: str) -> dict:
    """Normalize one file or file::symbol anchor and capture its digest."""
    raw = value.strip().replace("\\", "/")
    if not raw:
        raise ValueError("knowledge anchors must not be empty")
    path_text, separator, symbol = raw.partition("::")
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"knowledge anchor is outside repository: {value}") from exc
    if not resolved.is_file():
        raise ValueError(f"knowledge anchor file does not exist: {relative}")
    return {
        "path": relative,
        "symbol": symbol.strip() if separator and symbol.strip() else None,
        "digest": _file_digest(resolved),
    }


def _tokens(value: str) -> set[str]:
    """Return normalized lexical tokens for deterministic local retrieval."""
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(value)}


def _finding_id(claim: str, anchors: list[dict]) -> str:
    """Return a stable identity for an exact claim/anchor combination."""
    normalized = {
        "claim": " ".join(claim.split()).lower(),
        "anchors": [
            (anchor["path"], anchor.get("symbol"))
            for anchor in sorted(
                anchors,
                key=lambda item: (item["path"], item.get("symbol") or ""),
            )
        ],
    }
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()[:24]


@dataclass
class FindingStore:
    """Persist and retrieve bounded evidence-backed project findings."""

    root: Path

    def __post_init__(self) -> None:
        """Normalize repository scope once at the persistence boundary."""
        self.root = self.root.resolve()

    def remember(
        self,
        *,
        claim: str,
        anchors: list[str],
        evidence: str,
        applicability: str,
        confidence: str = "verified",
        invalidators: list[str] | None = None,
        supersedes: list[str] | None = None,
        source: str = "manual",
    ) -> dict:
        """Store or refresh one explicit project finding with provenance."""
        claim = " ".join(claim.strip().split())
        evidence = " ".join(evidence.strip().split())
        applicability = " ".join(applicability.strip().split())
        confidence = confidence.strip().lower()
        if not claim:
            raise ValueError("knowledge claim must not be empty")
        if not evidence:
            raise ValueError("knowledge evidence must not be empty")
        if not applicability:
            raise ValueError("knowledge applicability must not be empty")
        if confidence not in CONFIDENCE:
            allowed = ", ".join(sorted(CONFIDENCE))
            raise ValueError(f"knowledge confidence must be one of: {allowed}")
        if not anchors:
            raise ValueError("knowledge findings require at least one repository anchor")
        if len(anchors) > MAX_ANCHORS:
            raise ValueError(f"knowledge findings support at most {MAX_ANCHORS} anchors")

        normalized_anchors = [self._normalize_anchor(value) for value in anchors]
        finding_id = _finding_id(claim, normalized_anchors)
        now = int(time.time())
        invalidators = [
            " ".join(str(value).strip().split())
            for value in (invalidators or [])
            if str(value).strip()
        ][:MAX_INVALIDATORS]
        supersedes = [
            str(value).strip()
            for value in (supersedes or [])
            if str(value).strip()
        ]
        record = {
            "id": finding_id,
            "claim": claim,
            "anchors": normalized_anchors,
            "evidence": evidence,
            "applicability": applicability,
            "confidence": confidence,
            "invalidators": invalidators,
            "supersedes": supersedes,
            "source": source[:80],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

        path = knowledge_path(self.root)
        with _locked(path):
            payload = _load(self.root)
            findings = payload["findings"]
            previous = next(
                (
                    item
                    for item in findings
                    if isinstance(item, dict) and item.get("id") == finding_id
                ),
                None,
            )
            if previous:
                record["created_at"] = int(previous.get("created_at", now))
                record["version"] = int(previous.get("version", 1)) + 1
                findings[:] = [
                    item
                    for item in findings
                    if not (isinstance(item, dict) and item.get("id") == finding_id)
                ]
            for item in findings:
                if (
                    isinstance(item, dict)
                    and item.get("id") in supersedes
                    and item.get("id") != finding_id
                ):
                    item["superseded_by"] = finding_id
                    item["updated_at"] = now
            findings.append(record)
            if len(findings) > MAX_FINDINGS:
                findings[:] = findings[-MAX_FINDINGS:]
            payload["updated_at"] = now
            _atomic_write(path, payload)
        return self._materialize(record)

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        include_stale: bool = False,
    ) -> list[dict]:
        """Return relevant current findings ranked by deterministic lexical evidence."""
        if limit < 1:
            raise ValueError("knowledge recall limit must be at least 1")
        query_tokens = _tokens(query)
        ranked: list[tuple[float, dict]] = []
        for item in _load(self.root)["findings"]:
            if not isinstance(item, dict):
                continue
            materialized = self._materialize(item)
            if materialized["state"] != "active" and not include_stale:
                continue
            score = self._score(materialized, query_tokens)
            if query_tokens and score <= 0:
                continue
            materialized["score"] = round(score, 4)
            ranked.append((score, materialized))
        ranked.sort(
            key=lambda pair: (
                -pair[0],
                -int(pair[1].get("updated_at", 0)),
                pair[1].get("id", ""),
            )
        )
        return [item for _, item in ranked[:limit]]

    def status(self) -> dict:
        """Return durable-knowledge counts without exposing finding contents."""
        counts = {"active": 0, "stale": 0, "superseded": 0}
        findings = [
            item
            for item in _load(self.root)["findings"]
            if isinstance(item, dict)
        ]
        for item in findings:
            state = self._materialize(item)["state"]
            counts[state] = counts.get(state, 0) + 1
        return {
            "schema": SCHEMA,
            "total": len(findings),
            **counts,
            "path": str(knowledge_path(self.root)),
        }

    def _normalize_anchor(self, value: str) -> dict:
        """Normalize one anchor against this store's repository root."""
        return _normalize_anchor(self.root, value)

    def _materialize(self, item: dict) -> dict:
        """Return one finding with current staleness and provenance state."""
        result = dict(item)
        stale_reasons: list[str] = []
        anchors = item.get("anchors")
        anchors = anchors if isinstance(anchors, list) else []
        current_anchors: list[dict] = []
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            current = dict(anchor)
            path_text = str(anchor.get("path") or "")
            path = self.root / path_text
            expected = anchor.get("digest")
            current_digest = _file_digest(path)
            current["current_digest"] = current_digest
            if current_digest is None:
                stale_reasons.append(f"missing:{path_text}")
            elif expected and current_digest != expected:
                stale_reasons.append(f"changed:{path_text}")
            current_anchors.append(current)
        result["anchors"] = current_anchors
        if item.get("superseded_by"):
            state = "superseded"
        elif stale_reasons:
            state = "stale"
        else:
            state = "active"
        result["state"] = state
        result["stale_reasons"] = stale_reasons
        return result

    @staticmethod
    def _score(item: dict, query_tokens: set[str]) -> float:
        """Score one finding for a query without model calls or embeddings."""
        if not query_tokens:
            return 1.0
        claim = _tokens(str(item.get("claim") or ""))
        evidence = _tokens(str(item.get("evidence") or ""))
        applicability = _tokens(str(item.get("applicability") or ""))
        anchors = {
            token
            for anchor in item.get("anchors", [])
            if isinstance(anchor, dict)
            for token in _tokens(
                f"{anchor.get('path', '')} {anchor.get('symbol') or ''}"
            )
        }
        overlap = (
            4.0 * len(query_tokens & claim)
            + 2.0 * len(query_tokens & applicability)
            + 1.0 * len(query_tokens & evidence)
            + 2.0 * len(query_tokens & anchors)
        )
        confidence_bonus = {
            "verified": 0.30,
            "probable": 0.15,
            "speculative": 0.0,
        }.get(str(item.get("confidence")), 0.0)
        return overlap + confidence_bonus

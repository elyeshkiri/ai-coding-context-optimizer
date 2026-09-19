"""Compare repeated diagnostics and attach repository-graph context.

Delta is deliberately opt-in at the hook boundary. It stores only bounded,
structured diagnostics in the existing session ledger, never raw command output.
New/changed diagnostics can be mapped back to indexed symbols and nearby graph
edges so a compact delta can still point the agent at relevant source.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .repo_index import RepositoryIndex, build_index
from .state import diagnostic_snapshot, record_diagnostic_snapshot

_PYTEST = re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b", re.I)
_RUFF = re.compile(r"\bruff\s+(?:check|format)\b", re.I)
_PYTEST_SUMMARY = re.compile(
    r"^(FAILED|ERROR)\s+([^\s]+?::[^\s]+)(?:\s+-\s+(.+))?$",
    re.M,
)
_RUFF_LINE = re.compile(
    r"^(?P<path>[^:\n]+\.py):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<code>[A-Z][A-Z0-9]+)\s+(?P<message>.+)$",
    re.M,
)
_LOCATION = re.compile(
    r"(?P<path>[\w./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|cs)):"
    r"(?P<line>\d+)(?::\d+)?"
)


@dataclass(frozen=True)
class Diagnostic:
    """Represent diagnostic state and behavior."""
    identifier: str
    summary: str
    detail: str
    path: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        """Return a dictionary representation."""
        return asdict(self)


def _normalize_path(value: str | None) -> str | None:
    """Handle normalize path."""
    if not value:
        return None
    return value.replace("\\", "/").lstrip("./")


def family_for(command: str) -> str | None:
    """Handle family for."""
    if _PYTEST.search(command):
        return "pytest"
    if _RUFF.search(command):
        return "ruff"
    return None


def _pytest_diagnostics(text: str) -> list[Diagnostic]:
    """Handle pytest diagnostics."""
    out: list[Diagnostic] = []
    for match in _PYTEST_SUMMARY.finditer(text):
        status, identifier, message = match.groups()
        path = identifier.split("::", 1)[0]
        detail = match.group(0).strip()
        location = _LOCATION.search(detail)
        out.append(Diagnostic(
            identifier=identifier,
            summary=(message or status).strip(),
            detail=detail,
            path=_normalize_path(location.group("path") if location else path),
            line=int(location.group("line")) if location else None,
        ))
    return out


def _ruff_diagnostics(text: str) -> list[Diagnostic]:
    """Handle ruff diagnostics."""
    out: list[Diagnostic] = []
    for match in _RUFF_LINE.finditer(text):
        data = match.groupdict()
        path = _normalize_path(data["path"])
        line = int(data["line"])
        identifier = f"{path}:{line}:{data['col']}:{data['code']}"
        out.append(Diagnostic(
            identifier=identifier,
            summary=f"{data['code']} {data['message']}",
            detail=match.group(0).strip(),
            path=path,
            line=line,
        ))
    return out


def extract_diagnostics(command: str, text: str) -> tuple[str | None, list[Diagnostic]]:
    """Extract diagnostics."""
    family = family_for(command)
    if family == "pytest":
        return family, _pytest_diagnostics(text)
    if family == "ruff":
        return family, _ruff_diagnostics(text)
    return None, []


def _command_key(family: str, command: str) -> str:
    """Handle command key."""
    normalized = " ".join(command.split())
    return hashlib.sha256(f"{family}\0{normalized}".encode()).hexdigest()[:24]


def _restore(payload: dict | None) -> dict[str, Diagnostic]:
    """Handle restore."""
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("diagnostics")
    if not isinstance(raw, list):
        return {}
    out: dict[str, Diagnostic] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            diagnostic = Diagnostic(
                identifier=str(item["identifier"]),
                summary=str(item["summary"]),
                detail=str(item["detail"]),
                path=_normalize_path(item.get("path")),
                line=int(item["line"]) if item.get("line") is not None else None,
            )
        except (KeyError, TypeError, ValueError):
            continue
        out[diagnostic.identifier] = diagnostic
    return out


def _symbol_for(
    index: RepositoryIndex, diagnostic: Diagnostic,
):
    """Handle symbol for."""
    path = _normalize_path(diagnostic.path)
    if path and path in index.records:
        definitions = index.records[path].definitions
        if diagnostic.line is not None:
            containing = [
                item for item in definitions
                if item.start_line <= diagnostic.line <= item.end_line
            ]
            if containing:
                return path, min(
                    containing, key=lambda item: item.end_line - item.start_line
                )
        name = diagnostic.identifier.split("::")[-1].split("[", 1)[0]
        for item in definitions:
            if item.name == name:
                return path, item
        return path, None

    name = diagnostic.identifier.split("::")[-1].split("[", 1)[0]
    matches = index.find_symbols(name)
    if matches:
        return matches[0]
    return path, None


def graph_hint(
    root: Path, diagnostic: Diagnostic, *, index: RepositoryIndex | None = None,
) -> dict | None:
    """Handle graph hint."""
    index = index or build_index(root)
    path, symbol = _symbol_for(index, diagnostic)
    if path is None or path not in index.records:
        return None

    related: list[dict] = []
    for neighbor, edge in index.neighbors(path)[:4]:
        related.append({"path": neighbor, "reason": edge})

    return {
        "path": path,
        "line": diagnostic.line or (symbol.start_line if symbol else None),
        "symbol": (
            getattr(symbol, "qualified", None) or symbol.name
            if symbol is not None else None
        ),
        "related": related,
    }


def _render_change(
    status: str, diagnostic: Diagnostic, hint: dict | None,
) -> list[str]:
    """Render change."""
    lines = [f"{status} {diagnostic.identifier} — {diagnostic.summary}"]
    if status in {"NEW", "CHANGED"}:
        if diagnostic.detail and diagnostic.detail != lines[0]:
            lines.append(diagnostic.detail)
        if hint:
            suffix = f":{hint['line']}" if hint.get("line") else ""
            symbol = f"::{hint['symbol']}" if hint.get("symbol") else ""
            lines.append(f"source {hint['path']}{suffix}{symbol}")
            if hint.get("related"):
                rendered = ", ".join(
                    f"{item['path']} [{item['reason']}]"
                    for item in hint["related"][:3]
                )
                lines.append(f"related {rendered}")
    return lines


def apply_delta(
    root: Path,
    command: str,
    original: str,
    fallback: str,
    *,
    session_id: str | None,
) -> tuple[str, dict]:
    """Return a shorter structured delta when one exists, otherwise fallback."""
    family, current_list = extract_diagnostics(command, original)
    metadata = {
        "family": family,
        "used": False,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "resolved": 0,
    }
    if family is None or not session_id:
        return fallback, metadata

    key = _command_key(family, command)
    previous = _restore(diagnostic_snapshot(root, key, session_id))
    if not current_list and not previous:
        return fallback, metadata
    current = {item.identifier: item for item in current_list}
    record_diagnostic_snapshot(
        root,
        key,
        {
            "family": family,
            "diagnostics": [item.to_dict() for item in current_list[:200]],
        },
        session_id,
    )
    if not previous:
        return fallback, metadata

    statuses: list[tuple[str, Diagnostic]] = []
    for identifier, diagnostic in current.items():
        prior = previous.get(identifier)
        if prior is None:
            status = "NEW"
        elif prior.detail != diagnostic.detail or prior.summary != diagnostic.summary:
            status = "CHANGED"
        else:
            status = "UNCHANGED"
        metadata[status.lower()] += 1
        statuses.append((status, diagnostic))

    for identifier, diagnostic in previous.items():
        if identifier not in current:
            metadata["resolved"] += 1
            statuses.append(("RESOLVED", diagnostic))

    index: RepositoryIndex | None = None
    lines = [f"[token-saver delta: {family}]"]
    for status, diagnostic in statuses:
        hint = None
        if status in {"NEW", "CHANGED"}:
            try:
                if index is None:
                    index = build_index(root)
                hint = graph_hint(root, diagnostic, index=index)
            except (OSError, ValueError):
                hint = None
        lines.extend(_render_change(status, diagnostic, hint))

    rendered = "\n".join(lines) + "\n"
    if len(rendered.encode()) >= len(fallback.encode()):
        return fallback, metadata
    metadata["used"] = True
    return rendered, metadata

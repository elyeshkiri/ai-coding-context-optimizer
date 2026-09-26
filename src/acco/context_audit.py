"""Structural audit of always-on instruction, skill, memory, and MCP context."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path

from .audit import audit
from .estimate import Counter
from .mcp import probe_all

_EXTRA_FILES = (
    ("AGENTS.md", "agents_md", True),
    ("GEMINI.md", "gemini_md", True),
    (".github/copilot-instructions.md", "copilot", True),
)
_EXTRA_GLOBS = (
    (".cursor/rules/*.md", "cursor_rule", True),
    (".agents/skills/*/SKILL.md", "skill", False),
)
OVERSIZED_TOKENS = 2000
OVERSIZED_LINES = 220


def _digest(text: str) -> str:
    normalized = "\n".join(
        line.rstrip() for line in text.splitlines() if line.strip()
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def context_audit_report(
    root: Path,
    *,
    user_scope: bool = True,
    probe_mcp: bool = False,
    mcp_timeout: int = 15,
) -> dict:
    """Return a non-mutating structural audit of context configuration."""
    root = root.resolve()
    counter = Counter()
    base = audit(root, counter, user_scope=user_scope)
    rows: list[dict] = []
    seen: set[str] = set()

    for item in base.items:
        rows.append(asdict(item))
        seen.add(str(Path(item.path)))

    for rel, kind, always_on in _EXTRA_FILES:
        path = root / rel
        if path.is_file() and rel not in seen:
            text = path.read_text(encoding="utf-8", errors="replace")
            rows.append(
                {
                    "path": rel,
                    "kind": kind,
                    "tokens": counter.count(text, path.suffix),
                    "always_on": always_on,
                    "note": "",
                }
            )
            seen.add(rel)

    for pattern, kind, always_on in _EXTRA_GLOBS:
        for path in sorted(root.glob(pattern)):
            rel = str(path.relative_to(root))
            if rel in seen or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rows.append(
                {
                    "path": rel,
                    "kind": kind,
                    "tokens": counter.count(text, path.suffix),
                    "always_on": always_on,
                    "note": "portable/on-demand skill" if not always_on else "",
                }
            )
            seen.add(rel)

    digest_groups: dict[str, list[str]] = {}
    oversized: list[dict] = []
    for row in rows:
        path = Path(row["path"])
        actual = path if path.is_absolute() else root / path
        if not actual.is_file():
            continue
        text = actual.read_text(encoding="utf-8", errors="replace")
        digest_groups.setdefault(_digest(text), []).append(row["path"])
        lines = len(text.splitlines())
        if row["tokens"] >= OVERSIZED_TOKENS or lines >= OVERSIZED_LINES:
            oversized.append(
                {
                    "path": row["path"],
                    "tokens": row["tokens"],
                    "lines": lines,
                }
            )

    duplicates = [
        paths for paths in digest_groups.values() if len(paths) > 1
    ]
    mcp = []
    if probe_mcp and base.mcp_servers:
        for cost in probe_all(root, timeout=mcp_timeout):
            mcp.append(
                {
                    "name": cost.name,
                    "tokens": cost.tokens,
                    "tools": cost.tools,
                    "status": cost.status,
                    "measured": cost.measured,
                }
            )

    always_tokens = sum(
        int(row["tokens"]) for row in rows if row.get("always_on")
    )
    recommendations: list[dict] = []
    for item in oversized:
        recommendations.append(
            {
                "priority": "P1",
                "action": f"split or scope {item['path']}",
                "evidence": (
                    f"{item['tokens']} tokens / {item['lines']} lines"
                ),
            }
        )
    for group in duplicates:
        recommendations.append(
            {
                "priority": "P1",
                "action": "deduplicate instruction copies",
                "evidence": ", ".join(group),
            }
        )
    if base.mcp_servers and not probe_mcp:
        recommendations.append(
            {
                "priority": "P1",
                "action": "rerun with --probe-mcp",
                "evidence": (
                    f"{len(base.mcp_servers)} MCP server(s) configured"
                ),
            }
        )

    return {
        "schema": 1,
        "root": str(root),
        "always_on_tokens": always_tokens,
        "items": sorted(rows, key=lambda item: (-item["tokens"], item["path"])),
        "duplicates": duplicates,
        "oversized": oversized,
        "mcp_servers": list(base.mcp_servers),
        "mcp_probe": mcp,
        "recommendations": recommendations,
        "mutates_files": False,
    }

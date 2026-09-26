"""Portable terse-output skill generated from ACCO's safe output policy."""

from __future__ import annotations

from pathlib import Path

SKILL_TEXT = """---
name: acco-lean
description: Keep coding-agent final responses compact without weakening investigation or verification.
---

# ACCO Lean Mode

Use the smallest final response that still communicates the result and material caveats.

- Start with the result, changed file/symbol, command, or finding.
- Skip greetings, task restatement, tool narration, praise, and closing invitations.
- Do not reproduce unchanged code, logs, repository context, or prior facts.
- Summarize validation as compact facts such as `tests: 42 passed, 0 failed`.
- Keep lists short unless completeness is explicitly required.
- Preserve required code/diffs, diagnostics, safety information, and material caveats.
- Output brevity applies only to final prose. Never skip investigation or verification to save tokens.
- For code changes, start verification with the smallest existing directly relevant target, then broaden when failures, risk, or project policy require it.
- Never rerun an unchanged failing command without new evidence or a meaningful code/config/environment change.
"""


def skill_path(root: Path, host: str) -> Path:
    """Return the conventional skill location for one supported host family."""
    if host == "claude":
        return root / ".claude" / "skills" / "acco-lean" / "SKILL.md"
    if host == "agents":
        return root / ".agents" / "skills" / "acco-lean" / "SKILL.md"
    raise ValueError("host must be claude or agents")


def install_lean_skill(
    root: Path,
    *,
    host: str = "claude",
    force: bool = False,
) -> list[Path]:
    """Install the portable skill without overwriting unrelated user content."""
    hosts = ("claude", "agents") if host == "all" else (host,)
    paths: list[Path] = []
    for selected in hosts:
        path = skill_path(root, selected)
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current != SKILL_TEXT and not force:
                raise FileExistsError(
                    f"refusing to overwrite existing skill: {path}; use --force"
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SKILL_TEXT, encoding="utf-8")
        paths.append(path)
    return paths

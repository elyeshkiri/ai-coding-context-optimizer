"""Branding regression guard for the ACCO repository."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".toml", ".txt", ".rs"}
FORBIDDEN = re.compile("token" + r"[ _-]" + "saver", re.IGNORECASE)
ALLOWED_EXTERNAL = (
    "https://github.com/ppgranger/token-saver.git",
    "ppgranger/token-saver",
    "/tmp/ppgranger-token-saver",
)
# Local environments and build/tool caches are not repository text.
EXCLUDED_DIRS = {".git", ".venv", "venv", ".pytest_cache", ".ruff_cache", "build", "dist", "target", "node_modules"}


def test_legacy_brand_name_is_absent_from_repository_text():
    """Only the literal external ppgranger repository reference may use the old slug."""
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in parts):
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            inspected = line
            for allowed in ALLOWED_EXTERNAL:
                inspected = inspected.replace(allowed, "")
            if FORBIDDEN.search(inspected):
                violations.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert violations == [], "Legacy brand references remain:\n" + "\n".join(violations)

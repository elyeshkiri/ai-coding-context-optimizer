"""Branding regression guard for the ACCO repository."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".toml", ".txt", ".rs"}
FORBIDDEN = re.compile("|".join(("Token" + " Saver", "token" + "-saver", "token" + "_saver", "TOKEN" + "_SAVER")))
ALLOWED_EXTERNAL = (
    "https://github.com/ppgranger/token-saver.git",
    "ppgranger/token-saver",
    "/tmp/ppgranger-token-saver",
)


def test_legacy_brand_name_is_absent_from_repository_text():
    """Only the literal external ppgranger repository reference may use the old slug."""
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
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

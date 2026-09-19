"""Documentation quality gates for public Token Saver surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
import re

from token_saver.command_registry import DEFAULT_COMMAND_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "INTEGRATIONS.md",
    ROOT / "ARCHITECTURE.md",
    ROOT / "BENCHMARKING.md",
    ROOT / "OUTPUT_OPTIMIZATION.md",
    ROOT / "VALIDATION.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "QUICKSTART.md",
    ROOT / "docs" / "CLI_REFERENCE.md",
    ROOT / "docs" / "CONFIGURATION.md",
    ROOT / "docs" / "TROUBLESHOOTING.md",
    ROOT / "docs" / "UPGRADING.md",
)


def _project_version() -> str:
    """Read the package version without requiring TOML parsing in the test."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    assert match is not None
    return match.group(1)


def _legacy_cli_commands() -> set[str]:
    """Extract argparse subcommand literals from the compatibility CLI."""
    tree = ast.parse((ROOT / "src" / "token_saver" / "cli.py").read_text())
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            commands.add(first.value)
    return commands


def _markdown_targets(text: str) -> list[str]:
    """Extract ordinary inline Markdown link destinations."""
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def test_public_document_versions_match_package_metadata():
    """Landing, validation, and changelog must describe the released package."""
    version = _project_version()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    validation = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert readme.startswith(f"# Token Saver {version}\n")
    assert validation.startswith(f"# Validation for {version}\n")
    assert f"# {version} -" in changelog


def test_cli_reference_covers_all_registered_and_legacy_commands():
    """Every shipped command should be discoverable from the CLI reference."""
    reference = (ROOT / "docs" / "CLI_REFERENCE.md").read_text(encoding="utf-8")
    commands = set(DEFAULT_COMMAND_REGISTRY.names()) | _legacy_cli_commands()

    missing = sorted(name for name in commands if f"`{name}`" not in reference)
    assert missing == [], f"CLI reference is missing commands: {missing}"


def test_public_internal_markdown_links_resolve():
    """Relative links in the public documentation set must resolve to files."""
    broken: list[str] = []
    for document in PUBLIC_DOCS:
        text = document.read_text(encoding="utf-8")
        for raw in _markdown_targets(text):
            target = raw.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if " " in target and not target.startswith("<"):
                target = target.split(" ", 1)[0]
            target = target.strip("<>")
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{document.relative_to(ROOT)} -> {raw}")
    assert broken == [], "Broken documentation links:\n" + "\n".join(broken)


def test_docs_index_links_every_task_guide():
    """The docs hub should expose each task-oriented guide directly."""
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    for name in (
        "QUICKSTART.md",
        "CLI_REFERENCE.md",
        "CONFIGURATION.md",
        "TROUBLESHOOTING.md",
        "UPGRADING.md",
    ):
        assert f"]({name})" in index


def test_readme_points_to_docs_hub_and_core_references():
    """The project landing page should route users into maintained references."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in (
        "docs/README.md",
        "docs/QUICKSTART.md",
        "docs/CLI_REFERENCE.md",
        "docs/CONFIGURATION.md",
        "docs/TROUBLESHOOTING.md",
        "docs/UPGRADING.md",
        "ARCHITECTURE.md",
        "VALIDATION.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
    ):
        assert f"]({target})" in readme


def test_validation_keeps_non_publishable_swebench_limit_visible():
    """Documentation must not hide the unresolved end-to-end evidence gap."""
    validation = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    assert "non-publishable evidence" in validation
    assert "No 144-run aggregate savings claim" in validation


def test_setup_is_documented_as_idempotent_and_reversible():
    """The primary onboarding docs should state repair and uninstall guarantees."""
    quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    integrations = (ROOT / "INTEGRATIONS.md").read_text(encoding="utf-8")

    assert "Setup is idempotent" in quickstart
    assert "Token Saver-owned entries" in quickstart
    assert "idempotent" in integrations
    assert "preserving unrelated host" in integrations

"""Documentation quality gates for public ACCO surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
import re

from acco.cli import LEGACY_COMMANDS
from acco.command_registry import DEFAULT_COMMAND_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
COMMAND_DOCS = tuple(sorted((ROOT / "docs" / "commands").glob("*.md")))

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
    ROOT / "docs" / "JSON_OUTPUTS.md",
    ROOT / "docs" / "WORKED_EXAMPLE.md",
    ROOT / "docs" / "CONFIGURATION.md",
    ROOT / "docs" / "TROUBLESHOOTING.md",
    ROOT / "docs" / "UPGRADING.md",
    *COMMAND_DOCS,
)


def _project_version() -> str:
    """Read the package version without requiring TOML parsing in the test."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    assert match is not None
    return match.group(1)


def _legacy_cli_commands() -> set[str]:
    """Extract argparse subcommand literals from the compatibility CLI."""
    tree = ast.parse((ROOT / "src" / "acco" / "cli.py").read_text())
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


def _headings_outside_fences(text: str) -> list[str]:
    """Return Markdown headings while ignoring fenced code examples."""
    headings: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced and re.match(r"^#{1,6}\s+", line):
            headings.append(line.strip())
    return headings


def test_public_document_versions_match_package_metadata():
    """Landing, validation, and changelog must describe the released package."""
    version = _project_version()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    validation = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert readme.startswith(f"# ACCO {version}\n")
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
    assert "ACCO-owned entries" in quickstart
    assert "idempotent" in integrations
    assert "preserving unrelated host" in integrations



def test_legacy_command_constant_matches_parser_surface():
    """Merged top-level help must not drift from the legacy argparse surface."""
    assert set(LEGACY_COMMANDS) == _legacy_cli_commands()


def test_every_command_has_a_dedicated_reference_page():
    """All shipped commands need flags, exit codes, and output contracts."""
    commands = set(DEFAULT_COMMAND_REGISTRY.names()) | _legacy_cli_commands()
    pages = {path.stem: path for path in COMMAND_DOCS}

    assert set(pages) == commands
    required_sections = (
        "## Synopsis",
        "## Arguments and options",
        "## Exit codes",
        "## Output contract",
        "## Authoritative runtime help",
    )
    for name in sorted(commands):
        text = pages[name].read_text(encoding="utf-8")
        assert text.startswith(f"# `acco {name}`\n")
        for section in required_sections:
            assert section in text, f"{name} is missing {section}"


def test_cli_index_links_every_command_reference():
    """The command index must link every dedicated command page."""
    reference = (ROOT / "docs" / "CLI_REFERENCE.md").read_text(encoding="utf-8")
    commands = set(DEFAULT_COMMAND_REGISTRY.names()) | _legacy_cli_commands()
    for name in commands:
        assert f"](commands/{name}.md)" in reference


def test_docs_hub_links_high_value_narrative_and_machine_contracts():
    """The docs landing page should expose the new narrative and JSON contracts."""
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "](WORKED_EXAMPLE.md)" in index
    assert "](JSON_OUTPUTS.md)" in index


def test_worked_example_keeps_real_measurements_and_limitations_visible():
    """The end-to-end story must preserve both positive and negative evidence."""
    example = (ROOT / "docs" / "WORKED_EXAMPLE.md").read_text(encoding="utf-8")
    assert "14,214 estimated tokens" in example
    assert "264 estimated tokens" in example
    assert "45.6% more expensive" in example
    assert "demonstration, **not** a statistically publishable" in example
    assert "benchmark. The between-run spread" in example
    assert "independent verifier" in example


def test_benchmarking_documents_query_leakage_controls():
    """Future semantic holdouts must forbid answer-identity leakage."""
    benchmarking = (ROOT / "BENCHMARKING.md").read_text(encoding="utf-8")
    validation = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")

    assert "### Query-construction protocol" in benchmarking
    for phrase in (
        "target symbol/member name",
        "containing class/type/module name",
        "target file basename/path",
        "exact qualified symbol identity",
        "identifier-bearing",
        "trivial lexical baseline",
        "never rewrite queries after seeing retrieval misses",
    ):
        assert phrase in benchmarking
    assert "must not be read as evidence that semantic" in validation
    assert "identifier-bearing queries" in validation



def test_public_docs_do_not_repeat_section_headings():
    """Narrative docs should not contain accidental duplicated sections."""
    duplicates: list[str] = []
    for document in PUBLIC_DOCS:
        headings = _headings_outside_fences(
            document.read_text(encoding="utf-8")
        )
        seen: set[str] = set()
        for heading in headings:
            if heading in seen:
                duplicates.append(
                    f"{document.relative_to(ROOT)} -> {heading}"
                )
            seen.add(heading)
    assert duplicates == [], "Duplicate documentation headings:\n" + "\n".join(
        duplicates
    )


def test_current_docs_cover_v113_operational_surfaces():
    """Current docs must expose v1.13 recovery/proxy/optimizer workflows."""
    hub = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    upgrading = (ROOT / "docs" / "UPGRADING.md").read_text(encoding="utf-8")
    troubleshooting = (
        ROOT / "docs" / "TROUBLESHOOTING.md"
    ).read_text(encoding="utf-8")
    integrations = (ROOT / "INTEGRATIONS.md").read_text(encoding="utf-8")
    contracts = (ROOT / "docs" / "JSON_OUTPUTS.md").read_text(encoding="utf-8")

    assert "documentation map for ACCO 1." not in hub
    assert "## 1.13 recoverable optimization platform" in upgrading
    assert "## A `tsr_...` recovery handle cannot be resolved" in troubleshooting
    assert "## Provider proxy refuses to start or returns an upstream error" in troubleshooting
    assert "## Provider base-URL integration" in integrations
    for heading in (
        "## `recover --json`",
        "## `recovery-status --json`",
        "## `prefix-status --json`",
        "## `browser-context --json`",
        "## `optimize --json`",
    ):
        assert heading in contracts


def test_configuration_reference_has_unique_environment_rows():
    """Environment override tables should not silently duplicate config keys."""
    config = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    variables = re.findall(r"(?m)^\| `(ACCO_[A-Z0-9_]+)` \|", config)
    assert len(variables) == len(set(variables))


def test_semantic_evidence_docs_track_holdout_14_and_15_state():
    """Semantic docs must distinguish fresh #14 evidence from burned reruns."""
    validation = (ROOT / "VALIDATION.md").read_text(encoding="utf-8")
    benchmarking = (ROOT / "BENCHMARKING.md").read_text(encoding="utf-8")

    for text in (validation, benchmarking):
        assert "82.50%" in text
        assert "87.5%" in text
        assert "holdout #15" in text.lower()
        assert "fresh holdout #14 is required" not in text.lower()
    assert "first complete fresh run" in validation
    assert "development result must not be reported as fresh" in benchmarking

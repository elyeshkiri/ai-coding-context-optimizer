"""Tests for unified setup, doctor, config, and uninstall UX."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from token_saver.command_handlers.host import completion_main
from token_saver.guard import decide_read
from token_saver.hook import _config_from_env
from token_saver.integration_setup import (
    CODEX_END,
    CODEX_START,
    doctor_report,
    setup_integrations,
    uninstall_integrations,
)
from token_saver.runtime_config import settings_for


def _which(names):
    """Return a deterministic shutil.which replacement."""
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_setup_all_hosts_is_idempotent_and_preserves_unrelated_config(tmp_path):
    """Setup should own only Token Saver entries across supported hosts."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    (root / ".claude").mkdir()
    (root / ".cursor").mkdir()
    (home / ".codex").mkdir(parents=True)

    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "gh"}}}),
        encoding="utf-8",
    )
    (root / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"docs": {"command": "docs"}}}),
        encoding="utf-8",
    )
    (root / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [{"type": "command", "command": "other-hook"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    codex = home / ".codex" / "config.toml"
    codex.write_text('model = "gpt-test"\n', encoding="utf-8")

    first = setup_integrations(
        root, ("all",), home=home, which=_which({"claude", "cursor", "codex"})
    )
    second = setup_integrations(
        root, ("all",), home=home, which=_which({"claude", "cursor", "codex"})
    )

    assert first["configured_hosts"] == ["claude", "cursor", "codex"]
    assert second["configured_hosts"] == ["claude", "cursor", "codex"]
    assert (root / ".token-saver.toml").is_file()

    claude_mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert set(claude_mcp["mcpServers"]) == {"github", "token-saver"}
    assert claude_mcp["mcpServers"]["token-saver"]["args"] == [
        "serve",
        str(root.resolve()),
    ]

    cursor_mcp = json.loads(
        (root / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    )
    assert set(cursor_mcp["mcpServers"]) == {"docs", "token-saver"}

    settings = json.loads(
        (root / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        hook["command"]
        for entries in settings["hooks"].values()
        for entry in entries
        for hook in entry.get("hooks", [])
    ]
    assert commands.count("token-saver hook") == 4
    assert "other-hook" in commands

    codex_text = codex.read_text(encoding="utf-8")
    assert 'model = "gpt-test"' in codex_text
    assert codex_text.count(CODEX_START) == 1
    assert codex_text.count(CODEX_END) == 1


def test_uninstall_removes_only_owned_entries(tmp_path):
    """Uninstall should preserve unrelated host configuration and project config."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    setup_integrations(
        root, ("all",), home=home, which=_which({"claude", "cursor", "codex"})
    )
    mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    mcp["mcpServers"]["github"] = {"command": "gh"}
    (root / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

    skill = root / ".claude" / "skills" / "token-budget" / "SKILL.md"
    assert skill.is_file()

    result = uninstall_integrations(root, ("all",), home=home)

    assert result["removed_hosts"] == ["claude", "cursor", "codex"]
    assert not skill.exists()
    assert (root / ".token-saver.toml").exists()
    remaining = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert remaining["mcpServers"] == {"github": {"command": "gh"}}
    assert CODEX_START not in (home / ".codex" / "config.toml").read_text(
        encoding="utf-8"
    )


def test_uninstall_can_remove_project_config(tmp_path):
    """Project config removal should be explicit."""
    root = tmp_path / "repo"
    root.mkdir()
    setup_integrations(root, ("cursor",), which=_which({"cursor"}))

    uninstall_integrations(root, ("cursor",), remove_config=True)

    assert not (root / ".token-saver.toml").exists()


def test_setup_auto_detects_only_available_hosts(tmp_path):
    """Without --host, setup should configure only detected products."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()

    result = setup_integrations(
        root, home=home, which=_which({"cursor"})
    )

    assert result["requested_hosts"] == ["cursor"]
    assert (root / ".cursor" / "mcp.json").is_file()
    assert not (root / ".mcp.json").exists()
    assert not (home / ".codex" / "config.toml").exists()


def test_setup_refuses_unmanaged_codex_token_saver_section(tmp_path):
    """Setup should never silently overwrite a user-owned Codex MCP section."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[mcp_servers.token-saver]\ncommand = "custom"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unmanaged Token Saver Codex config"):
        setup_integrations(root, ("codex",), home=home, which=_which({"codex"}))

    assert 'command = "custom"' in path.read_text(encoding="utf-8")


def test_project_config_controls_runtime_and_env_overrides(tmp_path, monkeypatch):
    """Project TOML should be real runtime config, with environment taking priority."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".token-saver.toml").write_text(
        """[hooks]
guard = false
read_max_lines = 12
delta = true
min_lines = 88
keep_tail = 4
allow = ["generated/*"]
""",
        encoding="utf-8",
    )

    settings = settings_for(root)
    assert settings.guard is False
    assert settings.read_max_lines == 12
    assert settings.delta is True
    assert settings.min_lines == 88
    assert settings.keep_tail == 4

    hook_config = _config_from_env(root)
    assert hook_config.delta_enabled is True
    assert hook_config.min_lines == 88
    assert hook_config.keep_tail == 4

    monkeypatch.setenv("TOKEN_SAVER_DELTA", "0")
    monkeypatch.setenv("TOKEN_SAVER_MIN_LINES", "33")
    overridden = settings_for(root)
    assert overridden.delta is False
    assert overridden.min_lines == 33


def test_guard_uses_project_config(tmp_path):
    """Guard enablement and read limits should come from project config."""
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "large.py"
    source.write_text("\n".join(f"x{i} = {i}" for i in range(30)), encoding="utf-8")
    config = root / ".token-saver.toml"
    config.write_text("[hooks]\nguard = false\nread_max_lines = 5\n", encoding="utf-8")

    assert decide_read({"file_path": str(source)}, cwd=root) is None

    config.write_text("[hooks]\nguard = true\nread_max_lines = 5\n", encoding="utf-8")
    decision = decide_read({"file_path": str(source)}, cwd=root)
    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_doctor_reports_configured_hosts_and_index(tmp_path):
    """Doctor should consolidate CLI, host, config, and index health."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    (root / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    setup_integrations(root, ("cursor",), home=home, which=_which({"cursor", "token-saver"}))

    report = doctor_report(
        root, home=home, which=_which({"cursor", "token-saver"}), index=True
    )

    assert report["ready"] is True
    assert report["configured_hosts"] == ["cursor"]
    assert report["config_path"].endswith(".token-saver.toml")
    assert report["index"]["files"] >= 1


def test_completion_lists_new_integration_commands(capsys):
    """Shell completion should expose the productized integration commands."""
    assert completion_main(["bash"]) == 0
    output = capsys.readouterr().out
    assert "setup" in output
    assert "doctor" in output
    assert "uninstall" in output
    assert "${COMP_WORDS[COMP_CWORD]}" in output



def test_uninstall_preserves_modified_claude_skill(tmp_path):
    """Uninstall must not delete a user-modified skill file."""
    root = tmp_path / "repo"
    root.mkdir()
    setup_integrations(root, ("claude",), which=_which({"claude"}))
    skill = root / ".claude" / "skills" / "token-budget" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n# local note\n", encoding="utf-8")

    uninstall_integrations(root, ("claude",))

    assert skill.exists()
    assert "# local note" in skill.read_text(encoding="utf-8")

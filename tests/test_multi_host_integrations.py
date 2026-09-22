"""Coverage for extended coding-agent host integrations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from token_saver.host_configs import (
    HERMES_END,
    HERMES_START,
    antigravity_mcp_path,
    copilot_cli_config_path,
    copilot_mcp_path,
    hermes_config_path,
    openclaw_config_path,
    opencode_mcp_path,
)
from token_saver.integration_setup import (
    detect_hosts,
    setup_integrations,
    uninstall_integrations,
)


def _which(names):
    """Return a deterministic executable detector."""
    return lambda name: f"/usr/bin/{name}" if name in names else None


def _openclaw_runner(home: Path, calls: list[list[str]]):
    """Return a fake OpenClaw CLI that mutates its documented MCP registry."""
    def run(argv: list[str]) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        path = openclaw_config_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {}
        )
        mcp = dict(payload.get("mcp", {}))
        servers = dict(mcp.get("servers", {}))
        if argv[:4] == ["openclaw", "mcp", "set", "token-saver"]:
            servers["token-saver"] = json.loads(argv[4])
        elif argv[:4] == ["openclaw", "mcp", "unset", "token-saver"]:
            servers.pop("token-saver", None)
        else:
            raise AssertionError(argv)
        mcp["servers"] = servers
        payload["mcp"] = mcp
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def _copilot_runner(home: Path, calls: list[list[str]]):
    """Return a fake Copilot CLI MCP registry implementation."""
    def run(argv: list[str]) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        path = copilot_cli_config_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {}
        )
        servers = dict(payload.get("mcpServers", {}))
        if argv[:3] == ["copilot", "mcp", "add"]:
            servers["token-saver"] = {
                "type": "local",
                "command": "token-saver",
                "args": ["serve", "."],
                "tools": ["*"],
            }
        elif argv == ["copilot", "mcp", "remove", "token-saver"]:
            servers.pop("token-saver", None)
        else:
            raise AssertionError(argv)
        payload["mcpServers"] = servers
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def test_extended_hosts_setup_detect_and_uninstall_preserve_unrelated_config(tmp_path):
    """All new host adapters should own only their Token Saver MCP entry."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()

    opencode = opencode_mcp_path(root)
    opencode.parent.mkdir(parents=True)
    opencode.write_text(
        json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "servers": {
                    "docs": {
                        "type": "remote",
                        "url": "https://example.invalid/mcp",
                    }
                }
            },
        }),
        encoding="utf-8",
    )

    copilot = copilot_mcp_path(root)
    copilot.parent.mkdir(parents=True)
    copilot.write_text(
        json.dumps({"servers": {"docs": {"command": "docs"}}}),
        encoding="utf-8",
    )

    antigravity = antigravity_mcp_path(root)
    antigravity.parent.mkdir(parents=True)
    antigravity.write_text(
        json.dumps({"mcpServers": {"docs": {"command": "docs"}}}),
        encoding="utf-8",
    )

    hermes = hermes_config_path(home)
    hermes.parent.mkdir(parents=True)
    hermes.write_text(
        "theme: dark\n"
        "mcp_servers:\n"
        "  docs:\n"
        '    command: "docs"\n',
        encoding="utf-8",
    )

    openclaw = openclaw_config_path(home)
    openclaw.parent.mkdir(parents=True)
    openclaw.write_text(
        json.dumps({
            "mcp": {
                "servers": {
                    "docs": {"command": "docs"},
                }
            }
        }),
        encoding="utf-8",
    )

    calls: list[list[str]] = []
    runner = _openclaw_runner(home, calls)
    hosts = ("opencode", "openclaw", "hermes", "copilot", "antigravity")
    executables = {"opencode", "openclaw", "hermes", "code", "agy"}

    first = setup_integrations(
        root,
        hosts,
        home=home,
        which=_which(executables),
        runner=runner,
    )
    second = setup_integrations(
        root,
        hosts,
        home=home,
        which=_which(executables),
        runner=runner,
    )

    assert first["configured_hosts"] == list(hosts)
    assert second["configured_hosts"] == list(hosts)

    opencode_data = json.loads(opencode.read_text(encoding="utf-8"))
    assert set(opencode_data["mcp"]["servers"]) == {"docs", "token-saver"}
    assert opencode_data["mcp"]["servers"]["token-saver"] == {
        "type": "local",
        "command": ["token-saver", "serve", str(root.resolve())],
    }

    copilot_data = json.loads(copilot.read_text(encoding="utf-8"))
    assert set(copilot_data["servers"]) == {"docs", "token-saver"}
    assert copilot_data["servers"]["token-saver"]["args"] == [
        "serve",
        str(root.resolve()),
    ]

    antigravity_data = json.loads(antigravity.read_text(encoding="utf-8"))
    assert set(antigravity_data["mcpServers"]) == {"docs", "token-saver"}

    hermes_text = hermes.read_text(encoding="utf-8")
    assert hermes_text.count(HERMES_START) == 1
    assert hermes_text.count(HERMES_END) == 1
    assert "  docs:" in hermes_text
    assert str(root.resolve()) in hermes_text

    openclaw_data = json.loads(openclaw.read_text(encoding="utf-8"))
    assert set(openclaw_data["mcp"]["servers"]) == {"docs", "token-saver"}
    assert calls.count([
        "openclaw",
        "mcp",
        "set",
        "token-saver",
        json.dumps(
            {
                "command": "token-saver",
                "args": ["serve", str(root.resolve())],
            },
            separators=(",", ":"),
        ),
    ]) == 2

    statuses = {
        item.name: item
        for item in detect_hosts(
            root,
            home=home,
            which=_which(executables),
        )
    }
    for name in hosts:
        assert statuses[name].detected is True
        assert statuses[name].configured is True

    result = uninstall_integrations(
        root,
        hosts,
        home=home,
        which=_which(executables),
        runner=runner,
    )
    assert result["removed_hosts"] == list(hosts)

    opencode_data = json.loads(opencode.read_text(encoding="utf-8"))
    assert set(opencode_data["mcp"]["servers"]) == {"docs"}
    copilot_data = json.loads(copilot.read_text(encoding="utf-8"))
    assert set(copilot_data["servers"]) == {"docs"}
    antigravity_data = json.loads(antigravity.read_text(encoding="utf-8"))
    assert set(antigravity_data["mcpServers"]) == {"docs"}
    assert HERMES_START not in hermes.read_text(encoding="utf-8")
    assert "  docs:" in hermes.read_text(encoding="utf-8")
    openclaw_data = json.loads(openclaw.read_text(encoding="utf-8"))
    assert set(openclaw_data["mcp"]["servers"]) == {"docs"}


def test_opencode_refuses_ambiguous_sibling_jsonc_config(tmp_path):
    """Setup should not create a competing OpenCode project config silently."""
    root = tmp_path / "repo"
    root.mkdir()
    sibling = root / ".opencode" / "opencode.jsonc"
    sibling.parent.mkdir(parents=True)
    sibling.write_text('{"mcp":{"servers":{}}}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="ambiguous precedence"):
        setup_integrations(
            root,
            ("opencode",),
            which=_which({"opencode"}),
        )

    assert not opencode_mcp_path(root).exists()


def test_hermes_refuses_unmanaged_token_saver_entry(tmp_path):
    """Hermes setup must never overwrite a user-owned server definition."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    path = hermes_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        "mcp_servers:\n"
        "  token-saver:\n"
        '    command: "custom"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unmanaged Hermes"):
        setup_integrations(
            root,
            ("hermes",),
            home=home,
            which=_which({"hermes"}),
        )

    assert 'command: "custom"' in path.read_text(encoding="utf-8")


def test_copilot_auto_detection_requires_extension_or_existing_mcp(tmp_path):
    """A generic VS Code installation should not imply GitHub Copilot usage."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    (root / ".vscode").mkdir()

    statuses = {
        item.name: item
        for item in detect_hosts(
            root,
            home=home,
            which=_which({"code"}),
        )
    }
    assert statuses["copilot"].detected is False

    extensions = home / ".vscode" / "extensions"
    (extensions / "github.copilot-chat-1.2.3").mkdir(parents=True)
    statuses = {
        item.name: item
        for item in detect_hosts(
            root,
            home=home,
            which=_which({"code"}),
        )
    }
    assert statuses["copilot"].detected is True


def test_openclaw_explicit_setup_requires_native_cli(tmp_path):
    """OpenClaw mutation should fail clearly when its validated CLI is unavailable."""
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="requires the openclaw executable"):
        setup_integrations(
            root,
            ("openclaw",),
            which=_which(set()),
        )


def test_copilot_cli_native_registry_is_idempotent_and_owned(tmp_path):
    """Copilot CLI should use its native registry without replacing user entries."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    calls: list[list[str]] = []
    runner = _copilot_runner(home, calls)

    first = setup_integrations(
        root,
        ("copilot",),
        home=home,
        which=_which({"copilot"}),
        runner=runner,
    )
    second = setup_integrations(
        root,
        ("copilot",),
        home=home,
        which=_which({"copilot"}),
        runner=runner,
    )

    assert first["configured_hosts"] == ["copilot"]
    assert second["configured_hosts"] == ["copilot"]
    assert calls.count([
        "copilot",
        "mcp",
        "add",
        "--tools",
        "*",
        "token-saver",
        "--",
        "token-saver",
        "serve",
        ".",
    ]) == 1

    config = json.loads(
        copilot_cli_config_path(home).read_text(encoding="utf-8")
    )
    assert config["mcpServers"]["token-saver"]["args"] == ["serve", "."]

    statuses = {
        item.name: item
        for item in detect_hosts(
            root,
            home=home,
            which=_which({"copilot"}),
        )
    }
    assert statuses["copilot"].detected is True
    assert statuses["copilot"].configured is True
    assert "copilot-cli" in statuses["copilot"].details

    uninstall_integrations(
        root,
        ("copilot",),
        home=home,
        which=_which({"copilot"}),
        runner=runner,
    )
    assert calls[-1] == ["copilot", "mcp", "remove", "token-saver"]
    config = json.loads(
        copilot_cli_config_path(home).read_text(encoding="utf-8")
    )
    assert "token-saver" not in config["mcpServers"]


def test_copilot_cli_refuses_unmanaged_same_name_entry(tmp_path):
    """Native Copilot setup must not overwrite an existing user-owned server."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    path = copilot_cli_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "mcpServers": {
                "token-saver": {
                    "command": "custom",
                    "args": ["serve"],
                    "tools": ["*"],
                }
            }
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unmanaged Copilot CLI"):
        setup_integrations(
            root,
            ("copilot",),
            home=home,
            which=_which({"copilot"}),
            runner=_copilot_runner(home, []),
        )

    assert json.loads(path.read_text(encoding="utf-8"))[
        "mcpServers"
    ]["token-saver"]["command"] == "custom"


def test_setup_all_targets_only_detected_extended_hosts(tmp_path):
    """The expanded all selector should not require every supported product."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    (root / ".opencode").mkdir()
    (home / ".hermes").mkdir(parents=True)

    result = setup_integrations(
        root,
        ("all",),
        home=home,
        which=_which({"opencode", "hermes"}),
    )

    assert result["requested_hosts"] == ["opencode", "hermes"]
    assert result["configured_hosts"] == ["opencode", "hermes"]
    assert opencode_mcp_path(root).is_file()
    assert HERMES_START in hermes_config_path(home).read_text(encoding="utf-8")

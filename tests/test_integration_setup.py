"""Tests for unified setup, doctor, config, and uninstall UX."""

from __future__ import annotations

import json

import pytest

from token_saver.command_handlers.host import completion_main
from token_saver.guard import decide_read
from token_saver.hook import _config_from_env
from token_saver.integration_setup import (
    CODEX_END,
    CODEX_START,
    detect_hosts,
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
    config_text = (root / ".token-saver.toml").read_text(encoding="utf-8")
    assert "[output]" in config_text
    assert 'task = "auto"' in config_text
    assert "adaptive = true" in config_text
    assert 'calibration_file = ".token-saver.output-calibration.json"' in config_text
    assert "telemetry = true" in config_text
    assert "[model_routing]" in config_text
    assert 'mode = "advisory"' in config_text
    assert 'current_model = ""' in config_text
    assert 'allowed_models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]' in config_text
    assert "min_savings = 0.05" in config_text
    assert "conservative = true" in config_text
    assert "[efficiency]" in config_text
    assert "continuity = true" in config_text
    assert "dedup = true" in config_text
    assert "waste_detection = true" in config_text
    assert "knowledge_read_avoidance = false" in config_text
    assert "cache_economics = false" in config_text
    assert "cache_expected_reuses = 2" in config_text
    assert "[ingress]" in config_text
    assert "threshold_tokens = 12000" in config_text
    assert "packet_tokens = 1600" in config_text
    assert "[retrieval]" in config_text
    assert "cache = true" in config_text
    assert "[tool_proxy]" in config_text
    assert "enabled = false" in config_text
    assert 'provider = "ollama"' in config_text
    assert "cache_max_entries = 64" in config_text

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
    assert commands.count("token-saver hook") == 6
    assert set(settings["hooks"]) >= {
        "UserPromptSubmit",
        "Stop",
        "StopFailure",
    }
    assert "other-hook" in commands

    codex_text = codex.read_text(encoding="utf-8")
    assert 'model = "gpt-test"' in codex_text
    assert codex_text.count(CODEX_START) == 1
    assert codex_text.count(CODEX_END) == 1


def test_doctor_detects_pre_telemetry_partial_claude_hook_install(tmp_path):
    """Missing Stop telemetry hooks should make Claude setup visibly incomplete."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(
        json.dumps({
            "hooks": {
                "PreToolUse": [{
                    "matcher": "Read|Bash",
                    "hooks": [{"type": "command", "command": "token-saver hook"}],
                }],
                "PostToolUse": [{
                    "matcher": "Bash|Read",
                    "hooks": [{"type": "command", "command": "token-saver hook"}],
                }],
                "SessionStart": [{
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [{"type": "command", "command": "token-saver hook"}],
                }],
                "UserPromptSubmit": [{
                    "hooks": [{"type": "command", "command": "token-saver hook"}],
                }],
            }
        }),
        encoding="utf-8",
    )
    (root / ".mcp.json").write_text(
        json.dumps({
            "mcpServers": {
                "token-saver": {
                    "command": "token-saver",
                    "args": ["serve", str(root.resolve())],
                }
            }
        }),
        encoding="utf-8",
    )

    claude = next(
        host
        for host in detect_hosts(
            root,
            home=home,
            which=_which({"claude"}),
        )
        if host.name == "claude"
    )

    assert claude.detected is True
    assert claude.configured is False


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

[output]
enabled = false
mode = "terse"
task = "review"
adaptive = false
min_tokens = 300
max_tokens = 900
calibration_file = "custom-calibration.json"
telemetry = false
""",
        encoding="utf-8",
    )

    settings = settings_for(root)
    assert settings.guard is False
    assert settings.read_max_lines == 12
    assert settings.delta is True
    assert settings.min_lines == 88
    assert settings.keep_tail == 4
    assert settings.output_policy is False
    assert settings.output_mode == "terse"
    assert settings.output_task == "review"
    assert settings.output_adaptive is False
    assert settings.output_min_tokens == 300
    assert settings.output_max_tokens == 900
    assert settings.output_calibration_file == "custom-calibration.json"
    assert settings.output_telemetry is False

    hook_config = _config_from_env(root)
    assert hook_config.delta_enabled is True
    assert hook_config.min_lines == 88
    assert hook_config.keep_tail == 4
    assert hook_config.output_policy_enabled is False
    assert hook_config.output_policy_mode == "terse"
    assert hook_config.output_policy_task == "review"
    assert hook_config.output_policy_adaptive is False
    assert hook_config.output_policy_min_tokens == 300
    assert hook_config.output_policy_max_tokens == 900
    assert hook_config.output_policy_calibration_file == "custom-calibration.json"
    assert hook_config.output_telemetry_enabled is False

    monkeypatch.setenv("TOKEN_SAVER_DELTA", "0")
    monkeypatch.setenv("TOKEN_SAVER_MIN_LINES", "33")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_POLICY", "1")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_MODE", "detailed")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_TASK", "coding")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_ADAPTIVE", "1")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_MIN_TOKENS", "450")
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_MAX_TOKENS", "1400")
    monkeypatch.setenv(
        "TOKEN_SAVER_OUTPUT_CALIBRATION_FILE",
        "learned.json",
    )
    monkeypatch.setenv("TOKEN_SAVER_OUTPUT_TELEMETRY", "1")
    overridden = settings_for(root)
    assert overridden.delta is False
    assert overridden.min_lines == 33
    assert overridden.output_policy is True
    assert overridden.output_mode == "detailed"
    assert overridden.output_task == "coding"
    assert overridden.output_adaptive is True
    assert overridden.output_min_tokens == 450
    assert overridden.output_max_tokens == 1400
    assert overridden.output_calibration_file == "learned.json"
    assert overridden.output_telemetry is True


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



def test_guard_allow_supports_repository_relative_globs(tmp_path):
    """Project allow patterns should match paths relative to the repository root."""
    root = tmp_path / "repo"
    generated = root / "generated"
    generated.mkdir(parents=True)
    source = generated / "large.py"
    source.write_text("\n".join(f"x{i} = {i}" for i in range(30)), encoding="utf-8")
    (root / ".token-saver.toml").write_text(
        '[hooks]\nguard = true\nread_max_lines = 5\nallow = ["generated/*"]\n',
        encoding="utf-8",
    )

    assert decide_read({"file_path": str(source)}, cwd=root) is None



def test_setup_preflight_prevents_partial_multi_host_mutation(tmp_path):
    """A later host conflict must not leave earlier hosts partially configured."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    cursor = root / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text('{"mcpServers": {"docs": {"command": "docs"}}}\n', encoding="utf-8")
    codex = home / ".codex" / "config.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text(
        '[mcp_servers.token-saver]\ncommand = "custom"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unmanaged Token Saver Codex config"):
        setup_integrations(
            root,
            ("all",),
            home=home,
            which=_which({"claude", "cursor", "codex"}),
        )

    assert not (root / ".mcp.json").exists()
    assert json.loads(cursor.read_text(encoding="utf-8")) == {
        "mcpServers": {"docs": {"command": "docs"}}
    }
    assert not (root / ".token-saver.toml").exists()



def test_efficiency_config_and_environment_overrides(tmp_path, monkeypatch):
    """Session-efficiency controls should resolve from TOML then environment."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".token-saver.toml").write_text(
        """[efficiency]
enabled = false
continuity = false
dedup = false
waste_detection = false
knowledge_read_avoidance = true
cache_economics = true
cache_expected_reuses = 4
cache_write_factor = 1.5
cache_read_factor = 0.2
cache_min_relative_savings = 0.12
""",
        encoding="utf-8",
    )

    settings = settings_for(root)
    assert settings.efficiency_enabled is False
    assert settings.continuity_enabled is False
    assert settings.cross_turn_dedup is False
    assert settings.waste_detection is False
    assert settings.knowledge_read_avoidance is True
    assert settings.cache_economics is True
    assert settings.cache_expected_reuses == 4
    assert settings.cache_write_factor == 1.5
    assert settings.cache_read_factor == 0.2
    assert settings.cache_min_relative_savings == 0.12

    hook_config = _config_from_env(root)
    assert hook_config.efficiency_enabled is False
    assert hook_config.continuity_enabled is False
    assert hook_config.cross_turn_dedup_enabled is False
    assert hook_config.waste_detection_enabled is False

    monkeypatch.setenv("TOKEN_SAVER_EFFICIENCY", "1")
    monkeypatch.setenv("TOKEN_SAVER_CONTINUITY", "1")
    monkeypatch.setenv("TOKEN_SAVER_CROSS_TURN_DEDUP", "1")
    monkeypatch.setenv("TOKEN_SAVER_WASTE_DETECTION", "1")
    monkeypatch.setenv("TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE", "0")
    monkeypatch.setenv("TOKEN_SAVER_CACHE_ECONOMICS", "0")
    monkeypatch.setenv("TOKEN_SAVER_CACHE_EXPECTED_REUSES", "7")
    monkeypatch.setenv("TOKEN_SAVER_CACHE_WRITE_FACTOR", "1.75")
    monkeypatch.setenv("TOKEN_SAVER_CACHE_READ_FACTOR", "0.15")
    monkeypatch.setenv("TOKEN_SAVER_CACHE_MIN_RELATIVE_SAVINGS", "0.2")
    overridden = settings_for(root)

    assert overridden.efficiency_enabled is True
    assert overridden.continuity_enabled is True
    assert overridden.cross_turn_dedup is True
    assert overridden.waste_detection is True
    assert overridden.knowledge_read_avoidance is False
    assert overridden.cache_economics is False
    assert overridden.cache_expected_reuses == 7
    assert overridden.cache_write_factor == 1.75
    assert overridden.cache_read_factor == 0.15
    assert overridden.cache_min_relative_savings == 0.2


def test_posttool_hook_observes_edit_and_write_for_continuity(tmp_path):
    """Setup should subscribe to Edit/Write without adding more hook processes."""
    root = tmp_path / "repo"
    root.mkdir()
    setup_integrations(root, ("claude",), which=_which({"claude"}))

    settings = json.loads(
        (root / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    post = settings["hooks"]["PostToolUse"]
    token_saver = next(
        entry
        for entry in post
        if any(
            hook.get("command") == "token-saver hook"
            for hook in entry.get("hooks", [])
        )
    )
    assert token_saver["matcher"] == "Bash|Read|Edit|Write"



def test_ingress_and_retrieval_cache_config_environment_overrides(
    tmp_path,
    monkeypatch,
):
    """Ingress and retrieval caching should resolve from TOML then environment."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".token-saver.toml").write_text(
        """[ingress]
enabled = true
threshold_tokens = 9000
packet_tokens = 1200

[retrieval]
cache = false
cache_max_entries = 12
""",
        encoding="utf-8",
    )

    settings = settings_for(root)
    assert settings.ingress_enabled is True
    assert settings.ingress_threshold_tokens == 9000
    assert settings.ingress_packet_tokens == 1200
    assert settings.retrieval_cache is False
    assert settings.retrieval_cache_max_entries == 12

    hook_config = _config_from_env(root)
    assert hook_config.ingress_enabled is True
    assert hook_config.ingress_threshold_tokens == 9000
    assert hook_config.ingress_packet_tokens == 1200

    monkeypatch.setenv("TOKEN_SAVER_INGRESS_OPTIMIZER", "0")
    monkeypatch.setenv("TOKEN_SAVER_INGRESS_THRESHOLD_TOKENS", "14000")
    monkeypatch.setenv("TOKEN_SAVER_INGRESS_PACKET_TOKENS", "1800")
    monkeypatch.setenv("TOKEN_SAVER_RETRIEVAL_CACHE", "1")
    monkeypatch.setenv("TOKEN_SAVER_RETRIEVAL_CACHE_MAX_ENTRIES", "90")
    overridden = settings_for(root)

    assert overridden.ingress_enabled is False
    assert overridden.ingress_threshold_tokens == 14000
    assert overridden.ingress_packet_tokens == 1800
    assert overridden.retrieval_cache is True
    assert overridden.retrieval_cache_max_entries == 90

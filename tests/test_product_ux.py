"""Tests for the frictionless beginner-facing ACCO product UX."""

from __future__ import annotations

import json
from pathlib import Path

import acco.product_ux as product
from acco.entry import main
from acco.integration_setup import setup_integrations, uninstall_integrations


def test_bare_acco_is_a_product_home_screen(tmp_path: Path, capsys):
    """No-argument ACCO should guide setup rather than dump expert commands."""
    previous = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        assert main([]) == 0
    finally:
        os.chdir(previous)
    output = capsys.readouterr().out
    assert "ACCO " in output
    assert "Get ready:" in output
    assert "acco setup" in output
    assert "Advanced commands: acco advanced" in output


def test_setup_installs_managed_lean_skill_and_safe_profile(tmp_path: Path):
    """Claude setup should enable the safe local stack without extra commands."""
    result = setup_integrations(
        tmp_path,
        ("claude",),
        home=tmp_path / "home",
        which=lambda name: f"/usr/bin/{name}" if name == "claude" else None,
    )

    config = (tmp_path / ".acco.toml").read_text(encoding="utf-8")
    lean = tmp_path / ".claude" / "skills" / "acco-lean" / "SKILL.md"
    assert result["profile"] == "safe"
    assert result["lean_skill"] == str(lean)
    assert lean.is_file()
    assert '[profile]\nmode = "safe"' in config
    assert "history_dedup = true" in config
    assert 'model_routing = "off"' in config

    uninstall_integrations(
        tmp_path,
        ("claude",),
        home=tmp_path / "home",
        which=lambda name: f"/usr/bin/{name}" if name == "claude" else None,
    )
    assert not lean.exists()


def test_setup_cli_finishes_with_index_and_health(tmp_path: Path, capsys):
    """One setup command should configure, index, and verify the project."""
    (tmp_path / "app.py").write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    assert main(
        [
            "setup",
            str(tmp_path),
            "--host",
            "cursor",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "safe"
    assert payload["ready"] is True
    assert payload["index"]["files"] >= 1
    assert payload["health"]["ready"] is True


def test_status_default_is_simple_but_ledger_is_preserved(tmp_path: Path, capsys):
    """The product status should replace the old view without deleting it."""
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    setup_integrations(
        tmp_path,
        ("cursor",),
        which=lambda name: f"/usr/bin/{name}" if name == "cursor" else None,
    )

    assert main(["status", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "ACCO ● ACTIVE" in output
    assert "context removed" in output
    assert "More detail:" in output

    assert main(["status", str(tmp_path), "--ledger"]) == 0
    ledger = capsys.readouterr().out
    assert "state " in ledger
    assert "remembered reads" in ledger


def test_demo_is_provider_free_and_builds_real_pack(tmp_path: Path, capsys):
    """The first-run demo should show retrieval value without calling a model."""
    (tmp_path / "auth.py").write_text(
        "def refresh_session(token):\n    return token\n",
        encoding="utf-8",
    )

    assert main(
        [
            "demo",
            str(tmp_path),
            "--query",
            "refresh session",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider_request_made"] is False
    assert payload["context_pack_tokens"] > 0
    assert "auth.py" in payload["selected_files"]


def test_start_auto_selects_single_agent_and_warms_index(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    """One detected host should make acco start need no additional selection."""
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        product.shutil,
        "which",
        lambda name: "/usr/bin/cursor" if name == "cursor" else None,
    )

    assert product.start_main(
        [str(tmp_path), "--dry-run", "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "cursor"
    assert payload["index"]["files"] >= 1


def test_start_remembers_explicit_preference(tmp_path: Path, monkeypatch):
    """A chosen start host should be reusable without changing project files."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    candidates = [
        {
            "name": "claude",
            "executable": "/usr/bin/claude",
            "configured": True,
            "provider_wrapper": True,
        },
        {
            "name": "codex",
            "executable": "/usr/bin/codex",
            "configured": True,
            "provider_wrapper": True,
        },
    ]
    assert product._select_agent(tmp_path, candidates, "codex") == "codex"
    product._save_preference(tmp_path, "codex")
    assert product._select_agent(tmp_path, candidates, None) == "codex"


def test_bootstrap_persists_cli_before_running_setup(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    """uvx bootstrap should install persistently before configuring the project."""
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        product.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    monkeypatch.setattr(
        product.subprocess,
        "run",
        lambda command, **kwargs: calls.append(list(command)) or Completed(),
    )

    import acco.command_handlers.host as host_handlers

    received: list[str] = []
    monkeypatch.setattr(
        host_handlers,
        "setup_main",
        lambda argv: received.extend(argv) or 0,
    )

    assert product.bootstrap_main([str(tmp_path), "--host", "cursor"]) == 0
    assert calls == [["uv", "tool", "install", "acco"]]
    assert received == [str(tmp_path), "--host", "cursor"]
    assert "persistent install ready via uv" in capsys.readouterr().out


def test_update_is_inspectable_and_does_not_mutate_by_default(
    monkeypatch,
    capsys,
):
    """Update should show the package-manager command unless --apply is explicit."""
    monkeypatch.setattr(
        product.shutil,
        "which",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    assert product.update_main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["manager"] == "uv"
    assert payload["command"] == ["uv", "tool", "upgrade", "acco"]
    assert payload["applied"] is False


def test_advanced_surface_keeps_power_commands_discoverable(capsys):
    """Simplifying onboarding must not hide the existing expert API."""
    assert main(["advanced"]) == 0
    output = capsys.readouterr().out
    assert "pack" in output
    assert "ranking-explain" in output
    assert "provider-proxy" in output

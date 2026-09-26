"""Windows-first compatibility tests for ACCO runtime and UX."""

from __future__ import annotations

from pathlib import Path

from acco.command_handlers.host import completion_main
import acco.state as state
import acco.wrapper as wrapper


def test_windows_state_dir_uses_localappdata(tmp_path: Path):
    """Windows state should live under LOCALAPPDATA instead of a Claude folder."""
    result = state._default_state_dir(
        platform_name="nt",
        environ={"LOCALAPPDATA": str(tmp_path / "Local")},
        home=tmp_path / "home",
    )

    assert result == tmp_path / "Local" / "ACCO"


def test_windows_state_dir_falls_back_to_appdata(tmp_path: Path):
    """APPDATA remains a safe fallback when LOCALAPPDATA is unavailable."""
    result = state._default_state_dir(
        platform_name="nt",
        environ={"APPDATA": str(tmp_path / "Roaming")},
        home=tmp_path / "home",
    )

    assert result == tmp_path / "Roaming" / "ACCO"


def test_explicit_state_dir_still_wins(monkeypatch, tmp_path: Path):
    """Existing ACCO_STATE_DIR deployments must keep their explicit location."""
    override = tmp_path / "custom-state"
    monkeypatch.setenv("ACCO_STATE_DIR", str(override))

    assert state.state_dir() == override


def test_powershell_completion_is_native_and_parseable(capsys):
    """Windows users should receive a native PowerShell completer definition."""
    assert completion_main(["powershell"]) == 0
    output = capsys.readouterr().out

    assert "Register-ArgumentCompleter -Native -CommandName acco" in output
    assert "$wordToComplete" in output
    assert "'setup'" in output
    assert "'start'" in output


def test_frozen_wrapper_reenters_acco_executable(monkeypatch, tmp_path: Path):
    """Standalone acco.exe must invoke provider-proxy as an ACCO subcommand."""
    plan = wrapper.build_wrap_plan(
        "claude",
        [],
        port=45678,
        executable=r"C:\Tools\claude.exe",
    )
    monkeypatch.setattr(wrapper.sys, "executable", r"C:\Tools\acco.exe")
    monkeypatch.setattr(wrapper.sys, "frozen", True, raising=False)

    argv = wrapper._provider_proxy_argv(tmp_path, plan, "off")

    assert argv[0] == r"C:\Tools\acco.exe"
    assert argv[1] == "provider-proxy"
    assert "-m" not in argv


def test_python_wrapper_keeps_module_entrypoint(monkeypatch, tmp_path: Path):
    """Normal Python installs should retain the existing module execution path."""
    plan = wrapper.build_wrap_plan("codex", [], port=45679)
    monkeypatch.setattr(wrapper.sys, "executable", "python")
    monkeypatch.delattr(wrapper.sys, "frozen", raising=False)

    argv = wrapper._provider_proxy_argv(tmp_path, plan, "off")

    assert argv[:4] == ["python", "-m", "acco.entry", "provider-proxy"]

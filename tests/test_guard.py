import pytest
from pathlib import Path

from token_saver.guard import decide_read, run
from token_saver.install import install, merge_hooks


def _big_source(path: Path, n: int = 300) -> Path:
    body = "def foo():\n    return 1\n\n" + "\n".join(f"x_{i} = {i}" for i in range(n))
    path.write_text(body)
    return path


def test_small_read_allowed(tmp_path):
    p = tmp_path / "small.py"
    p.write_text("def foo():\n    return 1\n")
    assert decide_read({"file_path": str(p)}) is None


def test_large_full_read_denied(tmp_path):
    p = _big_source(tmp_path / "big.py")
    decision = decide_read({"file_path": str(p)})
    assert decision is not None
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "blocked" in reason
    assert "def foo" in reason


def test_ranged_read_allowed(tmp_path):
    p = _big_source(tmp_path / "big.py")
    assert decide_read({"file_path": str(p), "offset": 1, "limit": 20}) is None
    assert decide_read({"file_path": str(p), "offset": 0, "limit": 20}) is None


def test_offset_zero_without_limit_is_still_a_full_read(tmp_path):
    p = _big_source(tmp_path / "big.py")
    decision = decide_read({"file_path": str(p), "offset": 0})
    assert decision is not None


def test_allowlist_skips_package_json(tmp_path):
    p = tmp_path / "package.json"
    p.write_text("{\n" + "\n".join(f'  "k{i}": {i},' for i in range(300)) + "\n}\n")
    assert decide_read({"file_path": str(p)}) is None


def test_duplicate_read_denied_by_efficiency_dedup_default(tmp_path):
    from token_saver.state import record_read
    from token_saver.guard import _digest

    p = _big_source(tmp_path / "mod.py")
    record_read(tmp_path, p, _digest(p.read_text()))
    decision = decide_read({"file_path": str(p)}, cwd=tmp_path)
    assert decision is not None
    assert "unchanged" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_duplicate_read_dedup_can_be_disabled(tmp_path, monkeypatch):
    from token_saver.state import record_read
    from token_saver.guard import _digest

    monkeypatch.setenv("TOKEN_SAVER_CROSS_TURN_DEDUP", "0")
    p = _big_source(tmp_path / "mod.py", n=10)
    record_read(tmp_path, p, _digest(p.read_text()))
    assert decide_read({"file_path": str(p)}, cwd=tmp_path) is None


def test_duplicate_read_denied_when_enabled(tmp_path, monkeypatch):
    from token_saver.state import record_read
    from token_saver.guard import _digest

    monkeypatch.setenv("TOKEN_SAVER_REREAD", "1")
    p = _big_source(tmp_path / "mod.py")
    record_read(tmp_path, p, _digest(p.read_text()))
    decision = decide_read({"file_path": str(p)}, cwd=tmp_path)
    assert decision is not None
    assert "unchanged" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_allow_env_glob(tmp_path, monkeypatch):
    p = _big_source(tmp_path / "generated.py")
    monkeypatch.setenv("TOKEN_SAVER_ALLOW", "generated.py")
    assert decide_read({"file_path": str(p)}) is None


def test_markdown_not_guarded(tmp_path):
    p = tmp_path / "NOTES.md"
    p.write_text("\n".join(f"# h {i}" for i in range(400)))
    assert decide_read({"file_path": str(p)}) is None


def test_guard_env_off(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_GUARD", "0")
    p = _big_source(tmp_path / "big.py")
    assert decide_read({"file_path": str(p)}) is None


def test_run_ignores_bash_without_a_command():
    assert run({"tool_name": "Bash", "tool_input": {}}) == (0, None)
    assert run({"tool_name": "Bash", "tool_input": {"command": 5}}) == (0, None)


def _bash(command, cwd):
    return run({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}})[1]


def _big_py(tmp_path, name="big.py", n=400):
    path = tmp_path / name
    path.write_text("\n".join(f"def f{i}():\n    return {i}" for i in range(n)) + "\n")
    return path


@pytest.mark.parametrize("template", [
    "cat {p}", "cat -n {p}", "cat {p} 2>&1", "  cat {p}  ", "cat 'big.py'", "cat ./big.py",
])
def test_bash_cat_of_large_source_is_denied_with_an_outline(tmp_path, template):
    path = _big_py(tmp_path)
    decision = _bash(template.format(p=path), tmp_path)
    assert decision is not None, template
    out = decision["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "blocked `cat`" in out["permissionDecisionReason"]
    assert "def f0" in out["permissionDecisionReason"]


def test_bash_cat_resolves_relative_paths_against_the_payload_cwd(tmp_path):
    _big_py(tmp_path)
    assert _bash("cat big.py", tmp_path) is not None


@pytest.mark.parametrize("command", [
    "cat {p} | head -20",          # already bounded
    "cat {p} > /tmp/copy.py",      # redirect, not a dump to the model
    "cat {p} && echo done",        # compound command
    "head -50 {p}",                # bounded
    "sed -n '1,40p' {p}",          # bounded
    "grep -n def {p}",             # search, not a dump
    "cat -x {p}",                  # unknown flag: not our business
    "cat $(echo {p})",             # shell expansion
    "cat *.py",                    # glob
    "echo cat {p}",                # not a cat invocation
])
def test_bash_commands_other_than_a_lone_cat_are_left_alone(tmp_path, command):
    path = _big_py(tmp_path)
    assert _bash(command.format(p=path), tmp_path) is None


def test_bash_cat_allows_small_files_docs_and_allowlisted_names(tmp_path):
    small = tmp_path / "small.py"
    small.write_text("def f():\n    return 1\n")
    doc = tmp_path / "notes.md"
    doc.write_text("line\n" * 500)
    makefile = tmp_path / "Makefile"
    makefile.write_text("x\n" * 500)
    missing = tmp_path / "nope.py"
    for target in (small, doc, makefile, missing):
        assert _bash(f"cat {target}", tmp_path) is None


def test_bash_cat_of_several_files_outlines_only_the_large_ones(tmp_path):
    big = _big_py(tmp_path)
    small = tmp_path / "small.py"
    small.write_text("def tiny():\n    return 1\n")
    reason = _bash(f"cat {small} {big}", tmp_path)["hookSpecificOutput"]["permissionDecisionReason"]
    assert str(big) in reason and str(small) not in reason


def test_bash_guard_respects_kill_switches_and_allowlist(tmp_path, monkeypatch):
    path = _big_py(tmp_path)
    monkeypatch.setenv("TOKEN_SAVER_GUARD", "0")
    assert _bash(f"cat {path}", tmp_path) is None
    monkeypatch.delenv("TOKEN_SAVER_GUARD")
    monkeypatch.setenv("TOKEN_SAVER_ALLOW", "big.py")
    assert _bash(f"cat {path}", tmp_path) is None
    monkeypatch.delenv("TOKEN_SAVER_ALLOW")
    monkeypatch.setenv("TOKEN_SAVER_READ_MAX_LINES", "5000")
    assert _bash(f"cat {path}", tmp_path) is None


def test_hook_dispatches_pre_tool_use_bash_to_the_guard(tmp_path):
    from token_saver.hook import run as hook_run
    path = _big_py(tmp_path)
    _, response = hook_run({
        "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": f"cat {path}"},
    })
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_install_registers_the_bash_pre_hook():
    from token_saver.install import merge_hooks
    pre = merge_hooks({})["hooks"]["PreToolUse"]
    assert [e["matcher"] for e in pre] == ["Read|Bash"]


def test_install_upgrades_old_post_matcher(tmp_path):
    from token_saver.install import merge_hooks
    old = {
        "hooks": {
            "PostToolUse": [{
                "matcher": "Bash|Grep|WebFetch",
                "hooks": [{"type": "command", "command": "token-saver hook"}],
            }]
        }
    }
    merged = merge_hooks(old)
    posts = merged["hooks"]["PostToolUse"]
    matchers = [e.get("matcher") for e in posts]
    assert "Bash|Read|Edit|Write" in matchers
    assert "Bash|Grep|WebFetch" not in matchers


def test_install_merges(tmp_path):
    root = tmp_path
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text('{"env": {"FOO": "1"}}\n')
    path = install(root)
    text = path.read_text()
    assert "token-saver hook" in text
    assert "FOO" in text
    # second install is idempotent
    install(root)
    data = merge_hooks({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "token-saver hook"}]}]}})
    posts = data["hooks"]["PostToolUse"]
    assert sum(
        1
        for e in posts
        if any(h.get("command") == "token-saver hook" for h in e.get("hooks", []))
    ) == 1

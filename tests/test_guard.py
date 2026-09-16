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


def test_duplicate_read_off_by_default(tmp_path):
    from token_saver.state import record_read
    from token_saver.guard import _digest

    p = _big_source(tmp_path / "mod.py")
    record_read(tmp_path, p, _digest(p.read_text()))
    decision = decide_read({"file_path": str(p)}, cwd=tmp_path)
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "unchanged" not in reason


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


def test_run_ignores_bash():
    assert run({"tool_name": "Bash", "tool_input": {}}) == (0, None)


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
    assert "Bash|Read" in matchers
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

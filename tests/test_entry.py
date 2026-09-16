import textwrap

from token_saver.entry import main


def test_dispatcher_preserves_legacy_commands(capsys):
    assert main(["budget", ".", "--window", "1000", "--no-user-scope"]) == 0
    assert "TOTAL_PLANNED" in capsys.readouterr().out


def test_dispatcher_exposes_pack(tmp_path, capsys):
    (tmp_path / "auth.py").write_text(textwrap.dedent("""
        def refresh_session(token: str) -> str:
            return rotate_token(token)
    """))
    assert main([
        "pack", str(tmp_path), "--query", "refresh session", "--max-tokens", "500"
    ]) == 0
    out = capsys.readouterr().out
    assert "TOKEN-SAVER CONTEXT PACK" in out
    assert "auth.py" in out

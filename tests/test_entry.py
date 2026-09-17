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


def test_dispatcher_exposes_output_policy(capsys):
    assert main(["output-policy", "--mode", "terse", "--max-tokens", "250"]) == 0
    out = capsys.readouterr().out
    assert "target <= 250 tokens" in out
    assert "Do not restate the task" in out


def test_dispatcher_exposes_output_save(tmp_path, capsys):
    response = tmp_path / "response.txt"
    response.write_text(
        "Sure!\n\nImplemented.\n\nImplemented.\n",
        encoding="utf-8",
    )
    assert main(["output-save", str(response), "--mode", "terse"]) == 0
    out = capsys.readouterr().out
    assert "Sure!" not in out
    assert out.count("Implemented.") == 1

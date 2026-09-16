"""Smoke tests: every subcommand runs and returns 0."""

import textwrap

import pytest

from token_saver.cli import main


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        textwrap.dedent(
            """
            import os

            def handler(req, timeout: float = 1.0) -> bytes:
                return b""
            """
        )
    )
    (tmp_path / "src" / "b.ts").write_text(
        "export async function load(id: string): Promise<void> {\n  return;\n}\n"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("export function nope() {}\n")
    return tmp_path


def test_map_to_stdout(repo, capsys):
    assert main(["map", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "## src/a.py" in out
    assert "def handler(req, timeout: float=1.0) -> bytes:" in out
    assert "export async function load(id: string): Promise<void> {" in out
    assert "node_modules" not in out, "ignored directories must stay out of the map"


def test_map_to_file(repo, tmp_path, capsys):
    out_file = tmp_path / "CODEMAP.md"
    assert main(["map", str(repo), "-o", str(out_file)]) == 0
    assert "## src/a.py" in out_file.read_text()
    assert "tokens" in capsys.readouterr().out


def test_map_is_much_smaller_than_the_sources_it_covers(tmp_path):
    """The per-file `## path` header only pays for itself on real files."""
    from token_saver.skeleton import build_map

    raw = 0
    for n in range(10):
        body = "\n".join(f"    step_{i}(self.value, {i})" for i in range(40))
        src = textwrap.dedent(
            f'''
            import os

            class Service{n}:
                def run(self, payload: dict) -> int:
            '''
        ) + body + "\n"
        (tmp_path / f"mod{n}.py").write_text(src)
        raw += len(src)

    mapped = build_map(tmp_path)
    assert len(mapped) < raw * 0.25, f"{len(mapped)} vs {raw}"
    assert "def run(self, payload: dict) -> int:" in mapped


def test_map_missing_path_returns_1(capsys):
    assert main(["map", "/definitely/not/here"]) == 1
    assert "not found" in capsys.readouterr().err


def test_estimate_file(repo, capsys):
    assert main(["estimate", "-f", str(repo / "src" / "a.py")]) == 0
    assert "tokens" in capsys.readouterr().out


def test_filter_from_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr(
        "sys.stdin", io.StringIO("\n".join(f"line {i}" for i in range(500)))
    )
    assert main(["filter", "--max-lines", "40"]) == 0
    out = capsys.readouterr().out
    assert len(out.splitlines()) < 60


def test_budget(capsys):
    assert main(["budget"]) == 0
    assert "TOTAL_PLANNED" in capsys.readouterr().out


def test_audit_runs_and_reports(repo, capsys):
    (repo / "CLAUDE.md").write_text("# Project\n- use pnpm\n")
    assert main(["audit", str(repo), "--no-user-scope"]) == 0
    out = capsys.readouterr().out
    assert "ALWAYS-ON CONTEXT" in out
    assert "CLAUDE.md" in out
    assert "VERDICT" in out


def test_audit_flags_an_oversized_claude_md(repo, capsys):
    (repo / "CLAUDE.md").write_text("\n".join(f"- rule {i}" for i in range(400)))
    main(["audit", str(repo), "--no-user-scope"])
    out = capsys.readouterr().out
    assert "TRIMS" in out
    assert "200-line guidance" in out


def test_audit_on_a_bare_directory(tmp_path, capsys):
    assert main(["audit", str(tmp_path), "--no-user-scope"]) == 0
    assert "nothing found" in capsys.readouterr().out


def test_audit_rejects_a_file(repo, capsys):
    assert main(["audit", str(repo / "src" / "a.py"), "--no-user-scope"]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_budget_measures_the_project(repo, capsys):
    (repo / "CLAUDE.md").write_text("\n".join(f"- rule {i}" for i in range(2000)))
    assert main(["budget", str(repo), "--no-user-scope"]) == 0
    out = capsys.readouterr().out
    assert "OVER" in out, "an oversized CLAUDE.md must show as over budget"


def test_budget_rejects_a_zero_window(capsys):
    """Regression: --window 0 raised ZeroDivisionError."""
    assert main(["budget", ".", "--window", "0"]) == 1
    assert "must be positive" in capsys.readouterr().err


def test_estimate_missing_file_is_a_clean_error(capsys):
    """Regression: this printed a FileNotFoundError traceback."""
    assert main(["estimate", "-f", "/definitely/not/here.md"]) == 1
    assert "not found" in capsys.readouterr().err


def test_map_on_a_file_is_a_clean_error(repo, capsys):
    """Regression: this silently produced an empty map."""
    assert main(["map", str(repo / "src" / "a.py")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_map_respects_max_tokens_flag(repo, capsys):
    from token_saver.estimate import estimate_tokens

    assert main(["map", str(repo), "--max-tokens", "150"]) == 0
    assert estimate_tokens(capsys.readouterr().out) <= 150


def test_outline_shrinks_a_file_and_reports_the_cut(repo, capsys):
    assert main(["outline", str(repo / "src" / "a.py")]) == 0
    captured = capsys.readouterr()
    assert "def handler(req, timeout: float=1.0) -> bytes:" in captured.out
    assert "smaller" in captured.err


def test_outline_quiet_suppresses_the_note(repo, capsys):
    assert main(["outline", str(repo / "src" / "a.py"), "-q"]) == 0
    assert capsys.readouterr().err == ""


def test_outline_missing_file(capsys):
    assert main(["outline", "/definitely/not/here.py"]) == 1
    assert "not found" in capsys.readouterr().err


def test_outline_output_is_smaller_than_the_source(tmp_path, capsys):
    src = tmp_path / "big.py"
    src.write_text(
        "\n".join(f"def f{i}(a, b):\n" + "\n".join(f"    step{j}()" for j in range(20))
                  for i in range(20))
    )
    main(["outline", str(src), "-q"])
    assert len(capsys.readouterr().out) < len(src.read_text()) / 2


def test_sessions_reports_when_there_are_no_transcripts(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("token_saver.sessions.projects_dir", lambda: tmp_path)
    assert main(["sessions", str(tmp_path)]) == 1
    assert "no session transcripts" in capsys.readouterr().err


def test_sessions_summarises_a_real_transcript(tmp_path, capsys, monkeypatch):
    import json

    from token_saver.sessions import project_slug

    project = tmp_path / project_slug(tmp_path / "proj")
    project.mkdir(parents=True)
    body = "def handler(req):\n" + "    work()\n" * 100
    records = [
        {"type": "assistant", "message": {
            "usage": {"cache_read_input_tokens": 900, "input_tokens": 100},
            "content": [{"type": "tool_use", "id": "t1", "name": "Read"}]}},
        {"type": "user",
         "message": {"content": [{"tool_use_id": "t1", "type": "tool_result"}]},
         "toolUseResult": {"file": {"filePath": "/a/b.py", "content": body}}},
    ]
    (project / "s.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    monkeypatch.setattr("token_saver.sessions.projects_dir", lambda: tmp_path)

    assert main(["sessions", str(tmp_path / "proj")]) == 0
    out = capsys.readouterr().out
    assert "SESSIONS ANALYSED: 1" in out
    assert "cache hit rate" in out
    assert "HYPOTHETICAL ONE-SHOT OUTLINE REDUCTION" in out

def test_refresh_if_stale_writes_codemap(repo, capsys):
    assert main(["map", str(repo), "--refresh-if-stale"]) == 0
    assert (repo / "CODEMAP.md").is_file()
    capsys.readouterr()
    # second call is fresh — should not fail
    assert main(["map", str(repo), "--refresh-if-stale"]) == 0


def test_mcp_prune_dry_run_is_zero_when_unused_unknown(tmp_path, capsys, monkeypatch):
    import json
    from token_saver.sessions import project_slug

    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"github": {"command": "npx"}}}\n')
    project = tmp_path / project_slug(tmp_path)
    project.mkdir(parents=True)
    (project / "s.jsonl").write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 1}, "content": []}}) + "\n")
    monkeypatch.setattr("token_saver.sessions.projects_dir", lambda: tmp_path)
    assert main(["mcp-prune", str(tmp_path)]) == 0
    assert main(["mcp-prune", str(tmp_path), "--apply"]) == 2

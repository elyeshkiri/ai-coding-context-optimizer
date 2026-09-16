"""The always-on auditor: what actually loads on every turn."""

import json
import textwrap

import pytest

from token_saver.audit import audit, find_imports, parse_frontmatter, strip_noncounting
from token_saver.estimate import Counter


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "deploy").mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# Project\n- use pnpm\n")
    (tmp_path / ".claude" / "rules" / "style.md").write_text("# Style\n- 2 spaces\n")
    (tmp_path / ".claude" / "rules" / "api.md").write_text(
        textwrap.dedent(
            """\
            ---
            paths:
              - "src/api/**/*.ts"
            ---
            # API
            - validate input
            """
        )
    )
    (tmp_path / ".claude" / "skills" / "deploy" / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: Ship to prod\n---\n" + "detail\n" * 100
    )
    return tmp_path


def _by_path(report, needle):
    return [i for i in report.items if needle in i.path]


def test_rule_without_paths_is_always_on(project):
    report = audit(project, Counter(), user_scope=False)
    style = _by_path(report, "style.md")[0]
    assert style.always_on is True


def test_path_scoped_rule_is_not_always_on(project):
    """The whole point of paths: frontmatter — it must not be counted per-turn."""
    report = audit(project, Counter(), user_scope=False)
    api = _by_path(report, "api.md")[0]
    assert api.always_on is False
    assert "path-scoped" in api.note


def test_skill_body_is_on_demand_but_frontmatter_is_not(project):
    report = audit(project, Counter(), user_scope=False)
    entries = _by_path(report, "SKILL.md")
    always = [e for e in entries if e.always_on]
    demand = [e for e in entries if not e.always_on]
    assert len(always) == 1 and len(demand) == 1
    assert demand[0].tokens > always[0].tokens, "the body is the expensive part"


def test_claude_md_over_the_line_limit_is_flagged(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("\n".join(f"- rule {i}" for i in range(300)))
    report = audit(tmp_path, Counter(), user_scope=False)
    assert "over the 200-line guidance" in _by_path(report, "CLAUDE.md")[0].note


def test_always_on_total_excludes_on_demand(project):
    report = audit(project, Counter(), user_scope=False)
    assert report.always_on > 0
    assert report.on_demand > 0
    assert report.always_on + report.on_demand == sum(i.tokens for i in report.items)


def test_mcp_servers_are_reported(project):
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {}, "sentry": {}}})
    )
    report = audit(project, Counter(), user_scope=False)
    assert report.mcp_servers == ["github", "sentry"]


def test_malformed_mcp_json_does_not_crash(project):
    (project / ".mcp.json").write_text("{not json")
    assert audit(project, Counter(), user_scope=False).mcp_servers == []


def test_empty_project_is_handled(tmp_path):
    report = audit(tmp_path, Counter(), user_scope=False)
    assert report.always_on == 0


def test_imports_are_followed_and_counted(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@docs/style.md\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "style.md").write_text("# Style\n" + "- rule\n" * 50)
    report = audit(tmp_path, Counter(), user_scope=False)
    imported = [i for i in report.items if i.kind == "import"]
    assert imported and imported[0].always_on, "imports load at launch, so they are always-on"


def test_import_cycles_terminate(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("@a.md\n")
    (tmp_path / "a.md").write_text("@CLAUDE.md\n")
    report = audit(tmp_path, Counter(), user_scope=False)
    assert len(report.items) < 10


# ------------------------------------------------------------------ helpers


def test_html_comments_are_not_counted():
    """Claude Code strips block comments before injecting, so they are free."""
    assert "maintainer" not in strip_noncounting("a <!-- maintainer note --> b")


def test_backticked_at_path_is_not_an_import():
    assert find_imports("see `@README` for details") == []
    assert find_imports("see @docs/x.md") == ["docs/x.md"]


def test_imports_in_fenced_blocks_are_skipped():
    assert find_imports("```\n@docs/x.md\n```\n") == []


def test_frontmatter_list_parsing():
    meta = parse_frontmatter('---\npaths:\n  - "src/**"\n  - "lib/**"\n---\nbody\n')
    assert meta["paths"] == ["src/**", "lib/**"]


def test_no_frontmatter():
    assert parse_frontmatter("# just a heading\n") == {}


def test_user_scope_skills_are_counted(tmp_path, monkeypatch):
    """Regression: found live — ~/.claude/skills was never scanned.

    A user-scope skill's frontmatter is read for discovery on every session,
    so it belongs in the always-on total just like a project skill.
    """
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "browser").mkdir(parents=True)
    (home / ".claude" / "skills" / "browser" / "SKILL.md").write_text(
        "---\nname: browser\ndescription: Drive a headless browser\n---\n"
        + "detail\n" * 200
    )
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))

    project = tmp_path / "proj"
    project.mkdir()
    report = audit(project, Counter(), user_scope=True)

    skills = [i for i in report.items if i.kind == "skill"]
    assert len(skills) == 2, "expected a discovery entry and a body entry"
    always = [s for s in skills if s.always_on][0]
    demand = [s for s in skills if not s.always_on][0]
    assert "user scope" in always.note
    assert 0 < always.tokens < demand.tokens


def test_user_scope_can_be_switched_off(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "browser").mkdir(parents=True)
    (home / ".claude" / "skills" / "browser" / "SKILL.md").write_text(
        "---\nname: browser\ndescription: x\n---\nbody\n"
    )
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    project = tmp_path / "proj"
    project.mkdir()
    assert audit(project, Counter(), user_scope=False).items == []

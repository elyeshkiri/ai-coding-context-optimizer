"""Evidence-coverage extractors: SQL, package.json, CI YAML, env templates.

Widens indexing beyond source code so migrations, scripts, CI jobs, and
documented env vars are real, selectable evidence -- not just invisible
file classes that ranking could never reach regardless of relevance.
"""

from __future__ import annotations

import subprocess
import textwrap

from token_saver.pack import build_context_pack
from token_saver.patch_context import build_diff_context
from token_saver.repo_index import _extract, build_index
from token_saver.security import inspect_path
from token_saver.skeleton import walk_repo


def test_sql_migration_extracts_table_and_references_as_calls():
    sql = textwrap.dedent("""
        CREATE TABLE "factory_runs" (
          id uuid primary key,
          experiment_id uuid references "factory_product_experiments"(id)
        );
    """)
    symbols, imports, calls, tokens, definitions = _extract(sql, ".sql", "drizzle/0052_x.sql")
    assert "factory_runs" in symbols
    table = next(d for d in definitions if d.name == "factory_runs")
    assert table.kind == "table"
    assert "factory_product_experiments" in table.calls


def test_package_json_extracts_scripts_and_dependencies():
    pkg = (
        '{"scripts": {"build": "next build", "factory:worker": "ts-node lib/factory/worker.ts"},'
        ' "dependencies": {"next": "^14.0.0"}}'
    )
    symbols, imports, calls, tokens, definitions = _extract(pkg, ".json", "package.json")
    assert {"build", "factory:worker"} <= set(symbols)
    assert "next" in imports
    build = next(d for d in definitions if d.name == "build")
    assert build.kind == "script"
    assert build.signature == "next build"


def test_package_json_malformed_degrades_to_no_symbols_not_a_crash():
    symbols, imports, calls, tokens, definitions = _extract("{not valid json", ".json", "package.json")
    assert symbols == [] and definitions == []


def test_generic_json_is_indexed_as_plain_text_without_symbols():
    # Arbitrary JSON (not package.json) has no generalizable "definition"
    # notion -- it's still walked/searchable, just without symbol extraction.
    symbols, imports, calls, tokens, definitions = _extract('{"a": {"b": 1}}', ".json", "tsconfig.json")
    assert symbols == [] and definitions == []


def test_github_workflow_yaml_extracts_job_ids():
    yml = textwrap.dedent("""
        name: factory-ci
        on: [push]
        jobs:
          lint:
            runs-on: ubuntu-latest
          test:
            runs-on: ubuntu-latest
    """)
    symbols, imports, calls, tokens, definitions = _extract(
        yml, ".yml", ".github/workflows/factory-ci.yml"
    )
    assert set(symbols) == {"lint", "test"}
    assert {d.kind for d in definitions} == {"ci-job"}


def test_non_workflow_yaml_gets_no_job_extraction():
    yml = "jobs:\n  lint:\n    runs-on: ubuntu-latest\n"
    symbols, imports, calls, tokens, definitions = _extract(yml, ".yml", "helm/values.yml")
    assert symbols == [] and definitions == []


def test_env_template_extracts_var_names_as_symbols():
    env = "# comment\nFACTORY_DISCOVERY_ENABLED=true\nFACTORY_CONTENT_AUTO_PUBLISH=false\n"
    symbols, imports, calls, tokens, definitions = _extract(env, ".example", ".env.example")
    assert set(symbols) == {"FACTORY_DISCOVERY_ENABLED", "FACTORY_CONTENT_AUTO_PUBLISH"}
    assert all(d.kind == "env-var" for d in definitions)


def test_env_example_is_indexable_but_real_env_files_stay_blocked(tmp_path):
    (tmp_path / ".env.example").write_text("FOO=placeholder\n")
    (tmp_path / ".env").write_text("FOO=real-secret-value\n")
    (tmp_path / ".env.local").write_text("FOO=also-real\n")
    assert inspect_path(tmp_path, tmp_path / ".env.example").allowed
    assert not inspect_path(tmp_path, tmp_path / ".env").allowed
    assert not inspect_path(tmp_path, tmp_path / ".env.local").allowed


def test_build_index_never_self_ingests_its_own_cache_file(tmp_path):
    # A cache_path living inside the indexed root must not be reparsed as a
    # source file now that .json is indexable -- it would never stabilize
    # (its own digest changes on every write) and would waste tokens.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    return 1\n")
    cache = tmp_path / "index.json"
    first = build_index(tmp_path, cache_path=cache)
    second = build_index(tmp_path, cache_path=cache)
    assert "index.json" not in first.records
    assert "index.json" not in second.records
    assert second.reparsed == 0


def test_pack_diff_style_query_can_select_migration_and_package_json(tmp_path):
    root = tmp_path
    (root / "drizzle").mkdir()
    (root / "drizzle" / "0001_experiments.sql").write_text(
        'CREATE TABLE "factory_product_experiments" (id uuid primary key);\n'
    )
    (root / "package.json").write_text(
        '{"scripts": {"factory:worker": "ts-node lib/factory/worker.ts"}}'
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)

    pack = build_context_pack(
        root, "factory_product_experiments migration worker script",
        max_tokens=1500, changed_boost=False,
    )
    assert "drizzle/0001_experiments.sql" in pack.selected_files
    assert "package.json" in pack.selected_files


def test_github_workflows_are_walked_despite_dot_directory_skip(tmp_path):
    # .git/.venv/.cache are VCS/tooling internals and correctly skipped as a
    # blanket "starts with dot" rule; .github is conventionally committed CI
    # config and must not fall under that same rule.
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")

    found = {p.relative_to(tmp_path).as_posix() for p in walk_repo(tmp_path, use_gitignore=False)}
    assert ".github/workflows/ci.yml" in found
    assert ".git/config" not in found


def test_mixed_diff_represents_every_evidence_category_within_budget(tmp_path):
    """Regression fixture for a real-world validation run: a diff shaped like
    a large new subsystem landing alongside a few surgical edits to existing
    code (the shape that originally exposed the empty-pack, starvation, and
    missing-evidence-class bugs fixed this session). Locks in that outcome
    without depending on the private repository the original diff came from.
    """
    root = tmp_path
    src = root / "src"
    src.mkdir()
    (src / "critical.py").write_text(
        "def refresh_session(user_id):\n    return {'id': user_id}\n"
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)

    # Everything below is the diff under review: one genuine edit to an
    # existing file, plus a large batch of brand-new files across every
    # reservable evidence category -- the shape that originally exposed the
    # empty-pack, starvation, and missing-evidence-class bugs this session.
    (src / "critical.py").write_text(
        "def refresh_session(user_id, force=False):\n    return {'id': user_id, 'force': force}\n"
    )
    (root / "drizzle").mkdir()
    (root / "drizzle" / "0001_experiments.sql").write_text(
        'CREATE TABLE "experiments" (id uuid primary key);\n'
    )
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_new_feature.py").write_text(
        "def test_new_feature():\n    assert True\n"
    )
    # A large batch of brand-new source files -- the "new subsystem" that
    # would otherwise dominate every other changed file's BM25 score.
    for i in range(30):
        big = "\n".join(
            f"def widget_handler_{i}_{j}(payload):\n    return payload\n" for j in range(20)
        )
        (src / f"new_module_{i}.py").write_text(big)
    subprocess.run(["git", "add", "."], cwd=root, check=True)

    result = build_diff_context(root, staged=True, max_tokens=2500)
    coverage = result["coverage"]

    assert "src/critical.py" in result["selected_files"]
    assert "force=False" in result["context"]
    assert coverage["by_category"]["database"]["selected"] >= 1
    assert coverage["by_category"]["ci"]["selected"] >= 1
    assert coverage["by_category"]["tests"]["selected"] >= 1
    assert result["estimated_tokens"] <= 2500
    # 30 new modules is deliberately more than can fit -- the pack must say
    # so explicitly rather than silently implying it saw everything.
    assert coverage["not_represented"]

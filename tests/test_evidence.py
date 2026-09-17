"""Evidence-coverage extractors: SQL, package.json, CI YAML, env templates.

Widens indexing beyond source code so migrations, scripts, CI jobs, and
documented env vars are real, selectable evidence -- not just invisible
file classes that ranking could never reach regardless of relevance.
"""

from __future__ import annotations

import subprocess
import textwrap

from token_saver.pack import build_context_pack
from token_saver.repo_index import _extract, build_index
from token_saver.security import inspect_path


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

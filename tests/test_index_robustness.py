import pytest

from token_saver import syntax
from token_saver.repo_index import build_index

# A long chained expression is a realistic shape for generated code (data
# tables, bundled/minified output). Every parser-backed language builds a tree
# as deep as the chain, and the tree walkers are recursive.
CHAIN = "+".join(["1"] * 3000)

DEEP_FILES = [
    ("generated.js", f"function ok() {{ return 1; }}\nvar table = {CHAIN};\n", "ok"),
    ("generated.go", f"package p\nfunc Ok() int {{ return 1 }}\nvar table = {CHAIN}\n", "Ok"),
    ("generated.rs", f"fn ok() -> i32 {{ 1 }}\nconst T: i32 = {CHAIN};\n", "ok"),
    ("Generated.java", f"class Generated {{ int ok() {{ return 1; }} int t = {CHAIN}; }}\n", "Generated"),
    ("Generated.cs", f"class Generated {{ int Ok() {{ return 1; }} int t = {CHAIN}; }}\n", "Generated"),
]


@pytest.mark.parametrize(
    "name,source,expected_symbol", DEEP_FILES, ids=[f[0] for f in DEEP_FILES],
)
def test_one_pathologically_deep_file_does_not_abort_repository_indexing(
    tmp_path, name, source, expected_symbol,
):
    # Regression: RecursionError from one file's tree walk escaped
    # build_index and aborted indexing of every other file in the repository.
    (tmp_path / name).write_text(source)
    (tmp_path / "other.py").write_text("def fine():\n    return 0\n")

    index = build_index(tmp_path, persist=False)

    assert set(index.records) == {name, "other.py"}
    names = {definition.name for definition in index.records[name].definitions}
    # The generic fallback still recovers declarations from the degraded file.
    assert expected_symbol in names
    assert "fine" in {d.name for d in index.records["other.py"].definitions}


def test_deeply_nested_python_file_does_not_abort_repository_indexing(tmp_path):
    (tmp_path / "generated.py").write_text(
        "def ok():\n    return 1\nt = " + "+".join(["1"] * 100_000) + "\n"
    )
    (tmp_path / "other.py").write_text("def fine():\n    return 0\n")

    index = build_index(tmp_path, persist=False)

    assert set(index.records) == {"generated.py", "other.py"}


@pytest.mark.parametrize("suffix", [".js", ".go", ".rs", ".java", ".cs"])
def test_structural_symbols_report_deep_nesting_as_value_error(suffix):
    with pytest.raises(ValueError, match="too deeply nested"):
        syntax.symbols(f"var t = {CHAIN};", suffix)


@pytest.mark.parametrize("suffix,source,expected", [
    (".go", 'package p\nimport "fmt"\nfunc Ok() int { return 1 }\n', "Ok"),
    (".rs", "use std::fmt;\nfn ok() -> i32 { 1 }\n", "ok"),
    (".java", "import java.util.List;\nclass Ok { int f() { return 1; } }\n", "Ok"),
    (".cs", "using System;\nclass Ok { int F() { return 1; } }\n", "Ok"),
    (".js", "function ok() { return 1; }\n", "ok"),
], ids=["go", "rust", "java", "csharp", "js"])
def test_missing_language_grammar_degrades_instead_of_aborting_indexing(
    tmp_path, monkeypatch, suffix, source, expected,
):
    # Regression: structured_imports() ran outside the ImportError fallback
    # that symbol extraction already had, so an environment missing one
    # grammar (a pruned install, --no-deps) could not index any repository
    # containing a file of that language.
    def missing(*_args, **_kwargs):
        raise ImportError("grammar not installed")

    monkeypatch.setattr(syntax, "_extra_language", missing)
    monkeypatch.setattr(syntax, "_language", missing)
    (tmp_path / f"m{suffix}").write_text(source)
    (tmp_path / "other.py").write_text("def fine():\n    return 0\n")

    index = build_index(tmp_path, persist=False)

    assert set(index.records) == {f"m{suffix}", "other.py"}
    names = {d.name for d in index.records[f"m{suffix}"].definitions}
    assert expected in names

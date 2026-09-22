import json
from types import SimpleNamespace

from acco import evaluate as evaluate_module
from acco.evaluate import evaluate_manifest


def _repo_and_manifest(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("def resolve_command():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def resolve_command():\n    return 2\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tasks": [{
        "id": "dispatch",
        "query": "how does a group resolve a subcommand",
        "files": ["src/real.py"],
        "symbols": ["resolve_command"],
    }]}))
    return manifest


def _stub_pack(monkeypatch, labels, files):
    pack = SimpleNamespace(
        selected_symbols=labels, selected_files=files,
        selected_symbol_identities=[], estimated_tokens=10,
    )
    monkeypatch.setattr(evaluate_module, "build_context_pack", lambda *a, **k: pack)


def test_bare_symbol_recall_is_satisfied_by_a_same_named_symbol_in_an_unrelated_file(
    tmp_path, monkeypatch,
):
    # Found on the second frozen holdout: a test file's own `resolve_command`
    # made bare-name recall 1.0 while the real method in the expected file was
    # never selected. The scoped metric must not be fooled by that.
    manifest = _repo_and_manifest(tmp_path)
    _stub_pack(
        monkeypatch,
        labels=["tests/test_x.py:resolve_command@1"],
        files=["src/real.py", "tests/test_x.py"],
    )

    result = evaluate_manifest(tmp_path, manifest)

    task = result["tasks"][0]
    assert task["symbol_recall"] == 1.0
    assert task["symbol_recall_in_expected_files"] == 0.0
    assert result["summary"]["mean_symbol_recall"] == 1.0
    assert result["summary"]["mean_symbol_recall_in_expected_files"] == 0.0


def test_scoped_symbol_recall_credits_a_symbol_found_in_the_expected_file(
    tmp_path, monkeypatch,
):
    manifest = _repo_and_manifest(tmp_path)
    _stub_pack(
        monkeypatch,
        labels=["tests/test_x.py:resolve_command@1", "src/real.py:resolve_command@1"],
        files=["src/real.py", "tests/test_x.py"],
    )

    result = evaluate_manifest(tmp_path, manifest)

    assert result["tasks"][0]["symbol_recall_in_expected_files"] == 1.0
    assert result["summary"]["mean_symbol_recall_in_expected_files"] == 1.0

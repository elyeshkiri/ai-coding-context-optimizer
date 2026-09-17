import json
import subprocess

import pytest

from token_saver.evaluate import evaluate_manifest


def _write_repo(path, name):
    path.mkdir()
    (path / f"{name}.py").write_text(
        f"def {name}_handler():\n    return '{name}'\n"
    )


def test_multi_repo_holdout_manifest(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _write_repo(repo_a, "alpha")
    _write_repo(repo_b, "beta")
    manifest = tmp_path / "holdout.json"
    manifest.write_text(json.dumps({
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
        },
        "repositories": {
            "alpha-repo": "repo-a",
            "beta-repo": {"path": "repo-b"},
        },
        "tasks": [
            {
                "id": "alpha-task",
                "repository": "alpha-repo",
                "query": "alpha handler",
                "files": ["alpha.py"],
                "symbols": ["alpha_handler"],
            },
            {
                "id": "beta-task",
                "repository": "beta-repo",
                "query": "beta handler",
                "files": ["beta.py"],
                "symbols": ["beta_handler"],
            },
        ],
    }))

    result = evaluate_manifest(
        tmp_path, manifest, max_tokens=1000, require_holdout=True
    )
    assert result["holdout_protocol_enforced"] is True
    assert set(result["repositories"]) == {"alpha-repo", "beta-repo"}
    assert result["summary"]["mean_file_recall"] == 1.0
    assert result["summary"]["mean_symbol_recall"] == 1.0


def test_holdout_mode_rejects_unfrozen_ground_truth(tmp_path):
    _write_repo(tmp_path / "repo", "alpha")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "repositories": {"repo": "repo"},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    }))
    with pytest.raises(ValueError, match="holdout evaluation requires"):
        evaluate_manifest(tmp_path, manifest, require_holdout=True)


def test_revision_pin_is_enforced(tmp_path):
    repo = tmp_path / "repo"
    _write_repo(repo, "alpha")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    actual = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    good = tmp_path / "good.json"
    good.write_text(json.dumps({
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
        },
        "repositories": {"repo": {"path": "repo", "revision": actual}},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    }))
    assert evaluate_manifest(
        tmp_path, good, max_tokens=1000, require_holdout=True
    )["tasks"][0]["revision"] == actual

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
        },
        "repositories": {"repo": {"path": "repo", "revision": "deadbeef"}},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    }))
    with pytest.raises(ValueError, match="revision mismatch"):
        evaluate_manifest(tmp_path, bad, require_holdout=True)

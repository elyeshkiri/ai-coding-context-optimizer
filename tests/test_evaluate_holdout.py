import json
import subprocess

import pytest

from acco.evaluate import evaluate_manifest, ground_truth_hash


def _write_repo(path, name):
    path.mkdir()
    (path / f"{name}.py").write_text(
        f"def {name}_handler():\n    return '{name}'\n"
    )


def _freeze(payload):
    protocol = payload.setdefault("protocol", {})
    protocol["ground_truth_frozen"] = True
    protocol["development_excluded"] = True
    protocol["frozen_at"] = "2026-09-17T12:00:00Z"
    protocol["ground_truth_sha256"] = ground_truth_hash(payload)
    return payload


def test_multi_repo_holdout_manifest(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _write_repo(repo_a, "alpha")
    _write_repo(repo_b, "beta")
    manifest = tmp_path / "holdout.json"
    payload = _freeze({
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
    })
    manifest.write_text(json.dumps(payload))

    result = evaluate_manifest(
        tmp_path, manifest, max_tokens=1000, require_holdout=True
    )
    assert result["holdout_protocol_enforced"] is True
    assert result["ground_truth_sha256"] == payload["protocol"]["ground_truth_sha256"]
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


def test_holdout_mode_detects_ground_truth_edits(tmp_path):
    _write_repo(tmp_path / "repo", "alpha")
    manifest = tmp_path / "manifest.json"
    payload = _freeze({
        "repositories": {"repo": "repo"},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    })
    payload["tasks"][0]["query"] = "changed after freeze"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="ground truth is not frozen or changed"):
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
    good_payload = _freeze({
        "repositories": {"repo": {"path": "repo", "revision": actual}},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    })
    good.write_text(json.dumps(good_payload))
    assert evaluate_manifest(
        tmp_path, good, max_tokens=1000, require_holdout=True
    )["tasks"][0]["revision"] == actual

    bad = tmp_path / "bad.json"
    bad_payload = _freeze({
        "repositories": {"repo": {"path": "repo", "revision": "deadbeef"}},
        "tasks": [{
            "repository": "repo",
            "query": "alpha handler",
            "files": ["alpha.py"],
        }],
    })
    bad.write_text(json.dumps(bad_payload))
    with pytest.raises(ValueError, match="revision mismatch"):
        evaluate_manifest(tmp_path, bad, require_holdout=True)

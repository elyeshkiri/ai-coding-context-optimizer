"""Validation and causal-arm tests for frozen semantic holdout 13."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from token_saver.semantic_holdout import (
    _trivial_lexical_files,
    _validate_leakage,
    evaluate_semantic_holdout,
    query_freeze_hash,
    semantic_ground_truth_hash,
    validate_semantic_holdout,
)
from token_saver.repo_index import build_index

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "semantic-holdout-13.frozen.json"
QUERY_FREEZE = ROOT / "benchmarks" / "semantic-holdout-13.query-freeze.json"


class _FakeEncoder:
    """Deterministic semantic encoder for three-arm evaluation tests."""

    def encode(self, sentences, *, normalize_embeddings=True):
        """Map behavior prose and the target implementation to one vector."""
        del normalize_embeddings
        vectors = []
        for sentence in sentences:
            lowered = sentence.lower()
            if (
                "expired credentials" in lowered
                or "stale_session_artifact" in lowered
            ):
                vectors.append([1.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0])
        return vectors


def test_checked_in_semantic_holdout_is_hash_frozen_and_leakage_audited():
    """The canonical suite must validate before any model/repository work."""
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    freeze = json.loads(QUERY_FREEZE.read_text(encoding="utf-8"))

    result = validate_semantic_holdout(payload, MANIFEST)

    assert result["query_freeze_sha256"] == (
        "4a0c3cda63524037e45985244d3a86ec5835e022c439874148b7f8608514ebce"
    )
    assert result["ground_truth_sha256"] == (
        "47428f5b9b6963211c70a80e8551a9d61e1cc23aba60f0d53edf61f47b3c5562"
    )
    assert query_freeze_hash(freeze) == result["query_freeze_sha256"]
    assert semantic_ground_truth_hash(payload) == result["ground_truth_sha256"]
    assert result["task_count"] == 24
    assert result["eligible_tasks"] == 22
    assert result["excluded_tasks"] == 2


def test_literal_answer_identity_leak_is_detected():
    """Declared answer identities must not occur literally in eligible queries."""
    task = {
        "query": "please inspect ExactTargetMember for this behavior",
        "forbidden_identifiers": ["ExactTargetMember", "target_file.py"],
    }

    assert _validate_leakage(task) == ["ExactTargetMember"]


def test_trivial_baseline_is_distinct_term_overlap_only(tmp_path):
    """The comparison baseline must not inherit Token Saver structural boosts."""
    (tmp_path / "a.py").write_text("def unrelated():\n    return 1\n")
    (tmp_path / "z.py").write_text(
        "# graceful shutdown keeps active sessions\ndef target():\n    return 2\n"
    )
    index = build_index(tmp_path, persist=False)

    selected = _trivial_lexical_files(
        index,
        "graceful shutdown active sessions",
        max_files=1,
    )

    assert selected == ["z.py"]


def test_three_arm_evaluator_can_recover_semantic_only_target(
    tmp_path, monkeypatch,
):
    """Hybrid semantics may recover a target missed by both lexical controls."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a_noise.py").write_text(
        "def ordinary_helper():\n    return 'routine bookkeeping'\n"
    )
    (repo / "z_target.py").write_text(
        "def stale_session_artifact(record):\n"
        "    return not record.timeout_elapsed\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )

    freeze = {
        "suite_version": 1,
        "repositories": {
            "fixture": {
                "repository": "fixture/repo",
                "path": "repo",
            }
        },
        "tasks": [
            {
                "id": "semantic-recovery",
                "repository": "fixture",
                "source_issue": {
                    "number": 1,
                    "url": "https://example.invalid/issues/1",
                },
                "query": "prevent expired credentials from being reused",
            }
        ],
    }
    freeze_path = tmp_path / "queries.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")

    manifest = {
        "suite_version": 1,
        "max_tokens": 500,
        "max_files": 1,
        "repositories": {
            "fixture": {
                "repository": "fixture/repo",
                "path": "repo",
            }
        },
        "tasks": [
            {
                **freeze["tasks"][0],
                "files": ["z_target.py"],
                "forbidden_identifiers": [
                    "z_target.py",
                    "stale_session_artifact",
                ],
                "eligible": True,
            }
        ],
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
            "semantic_natural_language": True,
            "query_frozen_before_ground_truth": True,
            "no_identifier_leakage": True,
            "frozen_at": "2026-09-20T00:00:00Z",
            "query_freeze_file": "queries.json",
            "query_freeze_commit": "0" * 40,
            "query_freeze_sha256": query_freeze_hash(freeze),
            "ground_truth_sha256": "",
            "baseline": "distinct-term-overlap@1",
            "embedding_model": "fixture-model",
        },
    }
    manifest["protocol"]["ground_truth_sha256"] = semantic_ground_truth_hash(
        manifest
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        "token_saver.semantic_retrieval._load_encoder",
        lambda _model: _FakeEncoder(),
    )

    result = evaluate_semantic_holdout(tmp_path, manifest_path)
    task = result["tasks"][0]

    assert task["lexical"]["file_recall"] == 0.0
    assert task["trivial_lexical"]["file_recall"] == 0.0
    assert task["semantic"]["file_recall"] == 1.0
    assert task["semantic_recovered"] is True
    assert result["summary"]["semantic_recovered_tasks"] == 1

"""Validation and causal-arm tests for frozen semantic holdout 13."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from acco.semantic_holdout import (
    _trivial_lexical_files,
    _validate_leakage,
    evaluate_semantic_holdout,
    merge_semantic_holdout_results,
    query_freeze_hash,
    semantic_ground_truth_hash,
    validate_semantic_holdout,
)
from acco.repo_index import build_index

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "semantic-holdout-13.frozen.json"
QUERY_FREEZE = ROOT / "benchmarks" / "semantic-holdout-13.query-freeze.json"
MANIFEST_14 = ROOT / "benchmarks" / "semantic-holdout-14.frozen.json"
QUERY_FREEZE_14 = ROOT / "benchmarks" / "semantic-holdout-14.query-freeze.json"
MANIFEST_15 = ROOT / "benchmarks" / "semantic-holdout-15.frozen.json"
QUERY_FREEZE_15 = ROOT / "benchmarks" / "semantic-holdout-15.query-freeze.json"
MANIFEST_16 = ROOT / "benchmarks" / "semantic-holdout-16.frozen.json"
QUERY_FREEZE_16 = ROOT / "benchmarks" / "semantic-holdout-16.query-freeze.json"


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
        "8cdf871ea2fcbe59161a332f1f0ce0f93b087a6c3560acebadb5ee338c4169bf"
    )
    assert result["ground_truth_sha256"] == (
        "dc6ea6c3641db573b5b05473f2bc4ee13e0f05a4f093cb86f803e68c7b265d25"
    )
    assert query_freeze_hash(freeze) == result["query_freeze_sha256"]
    assert semantic_ground_truth_hash(payload) == result["ground_truth_sha256"]
    assert result["task_count"] == 24
    assert result["eligible_tasks"] == 22
    assert result["excluded_tasks"] == 2


def test_semantic_holdout_14_is_hash_frozen_before_first_evaluation():
    """Holdout 14 must preserve its pre-ground-truth query freeze and cohort."""
    payload = json.loads(MANIFEST_14.read_text(encoding="utf-8"))
    freeze = json.loads(QUERY_FREEZE_14.read_text(encoding="utf-8"))

    result = validate_semantic_holdout(payload, MANIFEST_14)

    assert result["query_freeze_sha256"] == (
        "2b96b273353c0dd76da0dd8bcdcd7a0cdbb93ca253b43409ff4fee2734d95f4a"
    )
    assert result["ground_truth_sha256"] == (
        "c1d16ce0289305533055de2406143d692e82f7bca35e2fc47f054306d3f9ed92"
    )
    assert query_freeze_hash(freeze) == result["query_freeze_sha256"]
    assert semantic_ground_truth_hash(payload) == result["ground_truth_sha256"]
    assert result["task_count"] == 24
    assert result["eligible_tasks"] == 20
    assert result["excluded_tasks"] == 4


def test_semantic_holdout_15_is_hash_frozen_and_cohort_locked():
    """Holdout 15 must preserve its query freeze, ground truth, and exclusions."""
    payload = json.loads(MANIFEST_15.read_text(encoding="utf-8"))
    freeze = json.loads(QUERY_FREEZE_15.read_text(encoding="utf-8"))

    result = validate_semantic_holdout(payload, MANIFEST_15)

    assert result["query_freeze_sha256"] == (
        "2767d3cb3f9c6cc4f606f5a1a1f01bba2421b0bd076729a97a0501b4be736ae4"
    )
    assert result["ground_truth_sha256"] == (
        "54df820439ab107e22ce5375b7ce5d4f170e93f15180633ea86c1808abeb2b1f"
    )
    assert query_freeze_hash(freeze) == result["query_freeze_sha256"]
    assert semantic_ground_truth_hash(payload) == result["ground_truth_sha256"]
    assert result["task_count"] == 24
    assert result["eligible_tasks"] == 13
    assert result["excluded_tasks"] == 11


def test_semantic_holdout_16_is_frozen_before_first_evaluation():
    """Holdout 16 must preserve its untouched fresh query and ground-truth seals."""
    payload = json.loads(MANIFEST_16.read_text(encoding="utf-8"))
    freeze = json.loads(QUERY_FREEZE_16.read_text(encoding="utf-8"))

    result = validate_semantic_holdout(payload, MANIFEST_16)

    assert result["query_freeze_sha256"] == (
        "f485dac4cef84caeefadc477e932b28734e0d13111671f119f9b70dad387f958"
    )
    assert result["ground_truth_sha256"] == (
        "14fb1e24745a803482eebb3229c7f72bd1d26222f3a9cd3b09101b4f158352e9"
    )
    assert query_freeze_hash(freeze) == result["query_freeze_sha256"]
    assert semantic_ground_truth_hash(payload) == result["ground_truth_sha256"]
    assert result["task_count"] == 18
    assert result["eligible_tasks"] == 18
    assert result["excluded_tasks"] == 0


def test_literal_answer_identity_leak_is_detected():
    """Declared answer identities must not occur literally in eligible queries."""
    task = {
        "query": "please inspect ExactTargetMember for this behavior",
        "forbidden_identifiers": ["ExactTargetMember", "target_file.py"],
    }

    assert _validate_leakage(task) == ["ExactTargetMember"]


def test_trivial_baseline_is_distinct_term_overlap_only(tmp_path):
    """The comparison baseline must not inherit ACCO structural boosts."""
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

    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        "acco.semantic_retrieval._load_encoder",
        lambda _model: _FakeEncoder(),
    )

    result = evaluate_semantic_holdout(tmp_path, manifest_path)
    task = result["tasks"][0]

    assert task["lexical"]["file_recall"] == 0.0
    assert task["trivial_lexical"]["file_recall"] == 0.0
    assert task["semantic"]["file_recall"] == 1.0
    assert task["semantic_recovered"] is True
    assert result["summary"]["semantic_recovered_tasks"] == 1



def test_repository_shards_merge_to_original_evaluation(tmp_path, monkeypatch):
    """Repository sharding must preserve the original frozen evaluation result."""
    repositories = {}
    tasks = []
    for alias in ("alpha", "beta", "gamma"):
        repo = tmp_path / alias
        repo.mkdir()
        (repo / "a_noise.py").write_text(
            "def ordinary_helper():\n    return 'routine bookkeeping'\n",
            encoding="utf-8",
        )
        (repo / "z_target.py").write_text(
            "def stale_session_artifact(record):\n"
            "    return not record.timeout_elapsed\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            [
                "git", "-C", str(repo), "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid",
                "commit", "-qm", "fixture",
            ],
            check=True,
        )
        repositories[alias] = {
            "repository": f"fixture/{alias}",
            "path": alias,
        }
        tasks.append(
            {
                "id": f"{alias}-semantic-recovery",
                "repository": alias,
                "source_issue": {
                    "number": 1,
                    "url": f"https://example.invalid/{alias}/issues/1",
                },
                "query": "prevent expired credentials from being reused",
            }
        )

    freeze = {
        "suite_version": 1,
        "repositories": repositories,
        "tasks": tasks,
    }
    freeze_path = tmp_path / "queries.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")

    manifest = {
        "suite_version": 1,
        "max_tokens": 500,
        "max_files": 1,
        "repositories": repositories,
        "tasks": [
            {
                **task,
                "files": ["z_target.py"],
                "forbidden_identifiers": [
                    "z_target.py",
                    "stale_session_artifact",
                ],
                "eligible": task["repository"] != "gamma",
                "exclusion_reason": (
                    "fixture exclusion"
                    if task["repository"] == "gamma"
                    else None
                ),
            }
            for task in tasks
        ],
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
            "semantic_natural_language": True,
            "query_frozen_before_ground_truth": True,
            "no_identifier_leakage": True,
            "frozen_at": "2026-09-21T00:00:00Z",
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
    manifest_path = tmp_path / "semantic-holdout-99.frozen.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        "acco.semantic_retrieval._load_encoder",
        lambda _model: _FakeEncoder(),
    )

    full = evaluate_semantic_holdout(tmp_path, manifest_path)
    alpha = evaluate_semantic_holdout(
        tmp_path,
        manifest_path,
        repositories={"alpha"},
    )
    beta = evaluate_semantic_holdout(
        tmp_path,
        manifest_path,
        repositories={"beta"},
    )
    gamma = evaluate_semantic_holdout(
        tmp_path,
        manifest_path,
        repositories={"gamma"},
    )
    assert gamma["tasks"] == []
    assert gamma["repositories"] == {}
    assert gamma["excluded_tasks"][0]["repository"] == "gamma"
    merged = merge_semantic_holdout_results(
        [beta, gamma, alpha],
        manifest_path,
    )

    assert merged["suite"] == "semantic-holdout-99"
    assert merged["tasks"] == full["tasks"]
    assert merged["repositories"] == full["repositories"]
    assert merged["summary"] == full["summary"]
    assert merged["protocol"] == full["protocol"]

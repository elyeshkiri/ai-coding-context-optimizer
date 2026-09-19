"""Tests for ranking snapshots, stage-attributed diffs, and CI regression gates."""

from __future__ import annotations

import copy
import json
import textwrap

import pytest

from token_saver.command_handlers.evaluation import (
    ranking_diff_main,
    ranking_snapshot_main,
)
from token_saver.command_registry import DEFAULT_COMMAND_REGISTRY
from token_saver.ranking_regression import (
    build_ranking_snapshot,
    compare_ranking_snapshots,
    regression_violations,
)


def _repo(tmp_path):
    """Create a deterministic two-file repository for ranking snapshots."""
    (tmp_path / "auth.py").write_text(
        textwrap.dedent(
            """
            class SessionManager:
                def refresh_session(self, token):
                    return token
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "billing.py").write_text(
        textwrap.dedent(
            """
            class InvoiceService:
                def create_invoice(self, account):
                    return account
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def _manifest(tmp_path, *, expected: str = "billing.py"):
    """Write one evaluation-style manifest and return its path."""
    manifest = tmp_path / "ranking-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "suite_version": 1,
                "tasks": [
                    {
                        "id": "rank-one",
                        "query": "refresh session token",
                        "files": [expected],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_snapshot_retains_expected_file_below_top_limit(tmp_path):
    """Expected files should be retained even when outside the displayed top-N."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)

    snapshot = build_ranking_snapshot(root, manifest, max_files=1)

    task = snapshot["tasks"][0]
    expected = task["expected"][0]
    assert expected["path"] == "billing.py"
    assert expected["rank"] == 2
    assert expected["trace_complete"] is True
    assert len(task["ranking"]) == 2
    assert task["ranking"][0]["rank"] == 1
    assert task["ranking"][1]["path"] == "billing.py"


def test_snapshot_records_repository_revision_metadata(tmp_path):
    """Non-git repositories should explicitly record a null revision."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)

    snapshot = build_ranking_snapshot(root, manifest)

    assert snapshot["repositories"] == {"default": {"revision": None}}
    assert snapshot["ground_truth_sha256"]
    assert snapshot["config"]["trace_scores"] is True


def test_diff_attributes_rank_regression_to_stage_changes(tmp_path):
    """Expected-file rank movement should include per-stage contribution changes."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)
    baseline = build_ranking_snapshot(root, manifest, max_files=2)
    candidate = copy.deepcopy(baseline)

    before = candidate["tasks"][0]["expected"][0]
    before["rank"] = 5
    before["final_score"] -= 7.0
    before["stage_deltas"]["structural-authority"] = (
        before["stage_deltas"].get("structural-authority", 0.0) - 9.0
    )
    before["stage_deltas"]["graph-closure"] = (
        before["stage_deltas"].get("graph-closure", 0.0) + 2.0
    )

    report = compare_ranking_snapshots(baseline, candidate)
    item = report["tasks"][0]["files"][0]

    assert item["baseline_rank"] == 2
    assert item["candidate_rank"] == 5
    assert item["rank_delta"] == 3
    assert item["regression"] is True
    assert report["summary"]["regressed_files"] == 1
    assert report["summary"]["max_rank_drop"] == 3
    changes = {change["stage"]: change for change in item["stage_changes"]}
    assert changes["structural-authority"]["delta"] == pytest.approx(-9.0)
    assert changes["graph-closure"]["delta"] == pytest.approx(2.0)


def test_diff_detects_expected_file_disappearance(tmp_path):
    """An expected file disappearing from the candidate ranking is a regression."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)
    baseline = build_ranking_snapshot(root, manifest)
    candidate = copy.deepcopy(baseline)
    observation = candidate["tasks"][0]["expected"][0]
    observation["rank"] = None
    observation["final_score"] = None
    observation["stage_deltas"] = {}
    observation["trace_complete"] = False

    report = compare_ranking_snapshots(baseline, candidate)
    item = report["tasks"][0]["files"][0]

    assert item["regression"] is True
    assert item["rank_delta"] is None
    assert report["summary"]["missing_in_candidate"] == 1
    assert regression_violations(report, allowed_rank_drop=100)


def test_diff_rejects_different_ground_truth(tmp_path):
    """Snapshots from different task definitions must not be compared."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)
    baseline = build_ranking_snapshot(root, manifest)
    candidate = copy.deepcopy(baseline)
    candidate["ground_truth_sha256"] = "different"

    with pytest.raises(ValueError, match="ground truth hashes differ"):
        compare_ranking_snapshots(baseline, candidate)


def test_regression_gate_respects_allowed_rank_drop(tmp_path):
    """CI gating should permit bounded drift but reject larger downward movement."""
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)
    baseline = build_ranking_snapshot(root, manifest)
    candidate = copy.deepcopy(baseline)
    candidate["tasks"][0]["expected"][0]["rank"] = 4

    report = compare_ranking_snapshots(baseline, candidate)

    assert regression_violations(report, allowed_rank_drop=1)
    assert regression_violations(report, allowed_rank_drop=2) == []


def test_snapshot_and_diff_commands_are_registered_and_ci_capable(tmp_path, capsys):
    """CLI should write snapshots and fail only when requested regression gates fire."""
    assert {"ranking-snapshot", "ranking-diff"} <= set(
        DEFAULT_COMMAND_REGISTRY.names()
    )
    root = _repo(tmp_path / "repo")
    manifest = _manifest(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"

    assert ranking_snapshot_main(
        [
            str(manifest),
            "--path",
            str(root),
            "--max-files",
            "1",
            "--out",
            str(baseline_path),
        ]
    ) == 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(baseline)
    candidate["tasks"][0]["expected"][0]["rank"] = 6
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    result = ranking_diff_main(
        [
            str(baseline_path),
            str(candidate_path),
            "--json",
            "--fail-on-regression",
            "--allowed-rank-drop",
            "1",
        ]
    )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["regressed_files"] == 1
    assert payload["violations"][0]["path"] == "billing.py"

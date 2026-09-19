"""Tests for the GitHub Actions ranking-artifact collector edge script."""

from io import BytesIO
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest


def _collector_module():
    """Load the collector script as a module for pure helper tests."""
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "collect_ranking_artifacts.py"
    spec = importlib.util.spec_from_file_location("ranking_artifact_collector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collector_keeps_newest_artifact_per_pr_name(monkeypatch):
    """Workflow reruns should not count as independent PR history samples."""
    collector = _collector_module()
    payload = {
        "artifacts": [
            {
                "id": 30,
                "name": "ranking-regression-59",
                "expired": False,
                "created_at": "2026-09-20T10:00:00Z",
                "archive_download_url": "https://example.test/30.zip",
                "workflow_run": {"id": 300},
            },
            {
                "id": 29,
                "name": "ranking-regression-59",
                "expired": False,
                "created_at": "2026-09-20T09:00:00Z",
                "archive_download_url": "https://example.test/29.zip",
                "workflow_run": {"id": 290},
            },
            {
                "id": 20,
                "name": "ranking-regression-58",
                "expired": False,
                "created_at": "2026-09-19T10:00:00Z",
                "archive_download_url": "https://example.test/20.zip",
                "workflow_run": {"id": 200},
            },
            {
                "id": 10,
                "name": "other-artifact",
                "expired": False,
                "created_at": "2026-09-18T10:00:00Z",
                "archive_download_url": "https://example.test/10.zip",
                "workflow_run": {"id": 100},
            },
        ]
    }
    monkeypatch.setattr(collector, "_fetch_json", lambda url, token: payload)

    selected = collector.list_recent_ranking_artifacts(
        "owner/repo",
        "token",
        limit=10,
    )

    assert [item["id"] for item in selected] == [30, 20]
    assert [item["name"] for item in selected] == [
        "ranking-regression-59",
        "ranking-regression-58",
    ]


def test_collector_respects_artifact_limit(monkeypatch):
    """Collection should stop after the configured number of unique PR artifacts."""
    collector = _collector_module()
    payload = {
        "artifacts": [
            {
                "id": value,
                "name": f"ranking-regression-{value}",
                "expired": False,
                "created_at": "2026-09-20T10:00:00Z",
                "archive_download_url": f"https://example.test/{value}.zip",
            }
            for value in range(5, 0, -1)
        ]
    }
    monkeypatch.setattr(collector, "_fetch_json", lambda url, token: payload)

    selected = collector.list_recent_ranking_artifacts(
        "owner/repo",
        "token",
        limit=2,
    )

    assert [item["id"] for item in selected] == [5, 4]


def test_collector_extracts_nested_ranking_diff_from_zip():
    """Artifact ZIP layout should not require ranking-diff.json at archive root."""
    collector = _collector_module()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as bundle:
        bundle.writestr("evidence/ranking-diff.json", '{"summary": {}}')
        bundle.writestr("baseline-ranking.json", "{}")

    extracted = collector._extract_ranking_diff(buffer.getvalue())

    assert extracted == b'{"summary": {}}'


def test_collector_rejects_ambiguous_ranking_diff_archives():
    """Artifacts with multiple ranking-diff files should fail conservatively."""
    collector = _collector_module()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as bundle:
        bundle.writestr("a/ranking-diff.json", "{}")
        bundle.writestr("b/ranking-diff.json", "{}")

    with pytest.raises(ValueError, match="exactly one ranking-diff"):
        collector._extract_ranking_diff(buffer.getvalue())


def test_collector_requires_positive_limit(monkeypatch):
    """A nonpositive sample limit should fail before any API request."""
    collector = _collector_module()
    called = False

    def fake_fetch(url, token):
        """Record an unexpected request."""
        nonlocal called
        called = True
        return {"artifacts": []}

    monkeypatch.setattr(collector, "_fetch_json", fake_fetch)

    with pytest.raises(ValueError, match="limit must be positive"):
        collector.list_recent_ranking_artifacts("owner/repo", "token", limit=0)

    assert called is False

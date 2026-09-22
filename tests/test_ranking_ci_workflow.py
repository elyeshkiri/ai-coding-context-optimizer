"""Tests for the PR ranking-regression workflow contract."""

from pathlib import Path


def _workflow_text() -> str:
    """Read the checked-in CI workflow."""
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ranking_regression_job_is_pr_only_and_uses_base_sha():
    """PR ranking comparisons must use the immutable protected-base commit."""
    workflow = _workflow_text()

    assert "ranking-regression:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "ref: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "path: baseline" in workflow
    assert "path: candidate" in workflow


def test_ranking_regression_uses_base_manifest_for_both_snapshots():
    """A PR must not be able to redefine the ground truth used for its own diff."""
    workflow = _workflow_text()
    command = "acco ranking-snapshot baseline/benchmarks/context-quality.json"

    assert workflow.count(command) == 2
    assert "--path baseline" in workflow
    assert "--path candidate" in workflow


def test_ranking_regression_is_informational_but_persists_evidence():
    """Rank movement should surface without becoming an uncalibrated merge gate."""
    workflow = _workflow_text()

    assert "--fail-on-regression" not in workflow
    assert '--markdown >> "$GITHUB_STEP_SUMMARY"' in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "baseline-ranking.json" in workflow
    assert "candidate-ranking.json" in workflow
    assert "ranking-diff.json" in workflow
    assert "retention-days: 14" in workflow

"""Tests for ranking-gate calibration workflow invariants."""

from pathlib import Path


def _workflow_text(name: str) -> str:
    """Read one checked-in GitHub Actions workflow."""
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_calibration_workflow_runs_weekly_manually_and_self_verifies():
    """Calibration should be repeatable, scheduled, and dogfood workflow changes."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert '".github/workflows/ranking-calibration.yml"' in workflow
    assert "schedule:" in workflow
    assert 'cron: "17 5 * * 1"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "artifact_limit:" in workflow


def test_calibration_workflow_reads_ranking_artifacts_without_write_permissions():
    """History collection needs read-only repository/action permissions."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "ranking-regression-" in workflow
    assert "actions/artifacts/$artifact_id/zip" in workflow
    assert "gh run download" not in workflow
    assert "unzip -p" in workflow
    assert "ranking-history/$artifact_id.json" in workflow


def test_calibration_workflow_deduplicates_pr_artifacts_before_sampling():
    """Reruns of one PR should not count as independent calibration samples."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert "seen = set()" in workflow
    assert "if name in seen:" in workflow
    assert "seen.add(name)" in workflow


def test_calibration_workflow_targets_current_ground_truth_hash():
    """Old benchmark cohorts must not affect the current gate-readiness result."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert "--print-ground-truth-hash" in workflow
    assert "--ground-truth-sha" in workflow
    assert "steps.benchmark.outputs.ground_truth_sha256" in workflow


def test_calibration_workflow_publishes_summary_and_evidence():
    """Calibration should be visible in Actions and retained as an artifact."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert '--markdown >> "$GITHUB_STEP_SUMMARY"' in workflow
    assert "ranking-calibration.json" in workflow
    assert "selected-ranking-artifacts.tsv" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "retention-days: 30" in workflow


def test_pr_workflow_annotates_diff_with_reproducible_provenance():
    """Future history artifacts should identify PR/run/base/candidate provenance."""
    workflow = _workflow_text("ci.yml")

    for field in (
        '"pull_request": int(os.environ["PR_NUMBER"])',
        '"run_id": int(os.environ["RUN_ID"])',
        '"run_attempt": int(os.environ["RUN_ATTEMPT"])',
        '"base_sha": os.environ["BASE_SHA"]',
        '"candidate_sha": os.environ["CANDIDATE_SHA"]',
    ):
        assert field in workflow



def test_calibration_workflow_parses_tab_separated_artifact_rows():
    """Artifact rows should use Bash ANSI-C tab syntax rather than literal text."""
    workflow = _workflow_text("ranking-calibration.yml")

    assert "while IFS=$'\\t' read -r artifact_id artifact_name _created_at" in workflow
    assert "printf '\\\\t'" not in workflow

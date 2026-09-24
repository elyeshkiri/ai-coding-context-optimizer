"""Tests for the user-facing local A/B trial workflow."""

from __future__ import annotations

import json
import subprocess

import pytest

from acco.command_handlers.experiment import trial_main
from acco.trial import build_trial_suite, run_trial, summarize_trial


def _git(repo, *args):
    """Run Git in one temporary test repository."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _repo(tmp_path):
    """Create one committed repository suitable for isolated trial snapshots."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "trial@example.test")
    _git(repo, "config", "user.name", "Trial")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_build_trial_suite_is_paired_and_non_publishable(tmp_path):
    """A local trial should reuse the experiment protocol without posing as evidence."""
    repo = _repo(tmp_path)

    suite = build_trial_suite(
        repo,
        prompt="Change VALUE to 2.",
        verifier_commands=["python -c \"from pathlib import Path; assert '2' in Path('app.py').read_text()\""],
        trials=2,
    )

    assert suite["design"]["trials_per_task"] == 2
    assert suite["protocol"]["history_isolated"] is True
    assert suite["protocol"]["independent_verification"] is True
    assert suite["protocol"]["task_definitions_frozen"] is False
    assert suite["protocol"]["trial_only"] is True
    profiles = suite["runner"]["condition_profiles"]
    assert profiles["baseline"]["install_acco"] is False
    assert profiles["enabled"]["install_acco"] is True
    assert suite["tasks"][0]["revision"] == _git(repo, "rev-parse", "HEAD")
    assert suite["tasks"][0]["verifier"][0][0] == "python"


def test_trial_refuses_dirty_worktree_by_default(tmp_path):
    """Uncommitted user changes must not silently disappear from the comparison."""
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("VALUE = 99\n", encoding="utf-8")

    with pytest.raises(ValueError, match="working tree is dirty"):
        run_trial(
            repo,
            prompt="Change VALUE to 2.",
            verifier_commands=["python -c \"raise SystemExit(0)\""],
            runner_command="python -c \"raise SystemExit(0)\"",
            transcript_mode="path",
            dry_run=True,
        )


def test_trial_cli_dry_run_needs_no_model_call(tmp_path, capsys):
    """Dry-run should validate the real paired schedule without executing a runner."""
    repo = _repo(tmp_path)

    rc = trial_main(
        [
            str(repo),
            "--prompt",
            "Change VALUE to 2.",
            "--verify",
            "python -c \"raise SystemExit(0)\"",
            "--runner",
            "python -c \"raise SystemExit(0)\"",
            "--transcript-mode",
            "path",
            "--trials",
            "2",
            "--dry-run",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trial"]["paired_trials"] == 2
    assert payload["trial"]["run_count"] == 4
    assert {
        row["condition"] for row in payload["trial"]["schedule"]
    } == {"baseline", "enabled"}
    assert payload["manifest"] is None


def test_trial_summary_uses_success_denominator_and_blocks_claims():
    """Raw token reduction should remain descriptive without broad blind quality."""
    summary = summarize_trial(
        {
            "runs": [
                {
                    "condition": "baseline",
                    "success": True,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "tool_calls": 4,
                    "seconds": 2,
                },
                {
                    "condition": "enabled",
                    "success": True,
                    "input_tokens": 60,
                    "output_tokens": 10,
                    "tool_calls": 3,
                    "seconds": 1,
                },
            ]
        }
    )

    assert summary["conditions"]["baseline"]["total_tokens_per_success"] == 120
    assert summary["conditions"]["enabled"]["total_tokens_per_success"] == 70
    assert summary["comparison"]["input_tokens_per_success_reduction"] == pytest.approx(0.4)
    assert summary["comparison"]["total_tokens_per_success_reduction"] == pytest.approx(
        1 - 70 / 120
    )
    assert summary["evidence"]["claim_allowed"] is False
    assert summary["evidence"]["publishable"] is False

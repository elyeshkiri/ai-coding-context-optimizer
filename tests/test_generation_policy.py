"""Tests for deterministic automatic generation-policy selection."""

from __future__ import annotations

from token_saver.generation_policy import (
    automatic_output_policy,
    classify_output_task,
    explicit_output_mode,
)
from token_saver.state import load as load_state


def test_task_classifier_is_conservative_and_task_aware():
    """Strong task language should classify while vague follow-ups stay ambiguous."""
    assert classify_output_task("Fix the regression in logout refresh") == "debugging"
    assert classify_output_task("Review pull request 67 for architecture issues") == "review"
    assert classify_output_task("Implement automatic policy injection") == "coding"
    assert classify_output_task("Design the system architecture and roadmap") == "planning"
    assert classify_output_task("Why is context reduction different from API cost?") == "explanation"
    assert classify_output_task("go for the next move") is None


def test_explicit_output_mode_respects_user_verbosity_requests():
    """Direct brevity/detail requests should override the configured default."""
    assert explicit_output_mode("keep it short please") == "terse"
    assert explicit_output_mode("give me a comprehensive deep dive") == "detailed"
    assert explicit_output_mode("continue") is None


def test_automatic_policy_injects_once_and_inherits_ambiguous_followups(
    tmp_path, monkeypatch
):
    """Repeated turns in one task should not pay the full policy injection again."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    first = automatic_output_policy(
        root,
        "Implement automatic output policy injection",
        session_id="s1",
    )
    assert first is not None
    assert "OUTPUT TASK: coding." in first
    assert "target <= 600 tokens" in first

    assert automatic_output_policy(root, "go for the next move", session_id="s1") is None

    stored = load_state(root, "s1")["output_policy"]
    assert stored["task"] == "coding"
    assert stored["mode"] == "normal"
    assert stored["max_tokens"] == 600


def test_automatic_policy_reinjects_when_task_changes(tmp_path, monkeypatch):
    """A real task-class change should replace the active generation contract."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    automatic_output_policy(root, "Implement the cache", session_id="s1")
    changed = automatic_output_policy(
        root,
        "Review the pull request for correctness",
        session_id="s1",
    )

    assert changed is not None
    assert "OUTPUT TASK: review." in changed
    assert load_state(root, "s1")["output_policy"]["task"] == "review"


def test_new_task_language_drops_ambiguous_task_inheritance(tmp_path, monkeypatch):
    """Explicit task switches should not inherit an unrelated old task class."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    automatic_output_policy(root, "Implement the cache", session_id="s1")
    changed = automatic_output_policy(
        root,
        "new task: continue with something unrelated",
        session_id="s1",
    )

    assert changed is not None
    assert "OUTPUT TASK: general." in changed
    assert load_state(root, "s1")["output_policy"]["task"] == "general"


def test_explicit_detail_request_changes_mode_and_budget(tmp_path, monkeypatch):
    """User-requested detail should override a normal configured mode."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    note = automatic_output_policy(
        root,
        "Explain the evaluator in detail",
        session_id="s1",
        mode="normal",
    )

    assert note is not None
    assert "OUTPUT TASK: explanation." in note
    assert "target <= 2400 tokens" in note
    stored = load_state(root, "s1")["output_policy"]
    assert stored["mode"] == "detailed"
    assert stored["max_tokens"] == 2400


def test_policy_state_is_isolated_by_session(tmp_path, monkeypatch):
    """The same policy should still inject for a distinct host session."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    first = automatic_output_policy(root, "Implement caching", session_id="s1")
    second = automatic_output_policy(root, "Implement caching", session_id="s2")

    assert first is not None
    assert second is not None


def test_new_session_reset_reenables_policy_injection(tmp_path, monkeypatch):
    """Context resets should force the compact generation contract to be restored."""
    from token_saver.state import reset_session

    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    assert automatic_output_policy(root, "Implement caching", session_id="s1")
    assert automatic_output_policy(root, "continue", session_id="s1") is None

    reset_session(root, reads=True, session_id="s1")

    restored = automatic_output_policy(root, "continue", session_id="s1")
    assert restored is not None
    assert "OUTPUT TASK: general." in restored

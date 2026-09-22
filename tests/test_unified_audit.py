"""Tests for the consolidated ACCO audit surface."""

from acco.unified_audit import unified_audit_report


def test_unified_audit_collects_cross_layer_state(tmp_path, monkeypatch):
    """One report should expose context, retrieval, processor, and recovery state."""
    (tmp_path / "CLAUDE.md").write_text("# Project\n- use focused reads\n", encoding="utf-8")
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("acco.unified_audit.transcript_paths", lambda root: [])

    report = unified_audit_report(
        tmp_path,
        user_scope=False,
        client="claude-code",
    )

    assert report["root"] == str(tmp_path.resolve())
    assert report["context"]["always_on_tokens"] > 0
    assert "semantic" in report["retrieval"]
    assert "available" in report["fastpath"]
    assert report["processor_coverage"]["bash_calls"] == 0
    assert report["client_capabilities"]["client"]["client"] == "claude-code"
    assert report["recovery"]["initialized"] is False
    assert "end-to-end cost-per-success without paired evaluation" in report["evidence"]["not_claimed"]


def test_unified_audit_rejects_non_directory(tmp_path):
    """Audit should fail cleanly before touching telemetry for invalid roots."""
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    try:
        unified_audit_report(target, user_scope=False)
    except ValueError as exc:
        assert "not a directory" in str(exc)
    else:
        raise AssertionError("expected ValueError")

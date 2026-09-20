"""Tests for durable evidence-backed cross-session project knowledge."""

from __future__ import annotations

import pytest

from token_saver.knowledge import FindingStore


def _project(tmp_path, monkeypatch):
    """Create an isolated repository and private Token Saver state directory."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(
        "def refresh_session(token):\n    return token\n",
        encoding="utf-8",
    )
    return root


def test_remember_and_recall_verified_finding(tmp_path, monkeypatch):
    """A current anchored finding should survive across store instances."""
    root = _project(tmp_path, monkeypatch)
    first = FindingStore(root).remember(
        claim="Session refresh uses the auth helper",
        anchors=["auth.py::refresh_session"],
        evidence="refresh_session is the implementation entry point",
        applicability="Use when debugging session refresh behavior",
        confidence="verified",
    )

    recalled = FindingStore(root).recall("debug session refresh", limit=3)

    assert recalled[0]["id"] == first["id"]
    assert recalled[0]["state"] == "active"
    assert recalled[0]["anchors"][0]["path"] == "auth.py"
    assert recalled[0]["anchors"][0]["symbol"] == "refresh_session"
    assert recalled[0]["score"] > 0


def test_changed_anchor_invalidates_finding_by_default(tmp_path, monkeypatch):
    """Changing anchored source should quarantine stale knowledge from normal recall."""
    root = _project(tmp_path, monkeypatch)
    store = FindingStore(root)
    finding = store.remember(
        claim="Session refresh returns the token unchanged",
        anchors=["auth.py::refresh_session"],
        evidence="The function directly returns token",
        applicability="Use when reasoning about refresh behavior",
    )
    (root / "auth.py").write_text(
        "def refresh_session(token):\n    return token + '-rotated'\n",
        encoding="utf-8",
    )

    assert store.recall("refresh token") == []
    stale = store.recall("refresh token", include_stale=True)

    assert stale[0]["id"] == finding["id"]
    assert stale[0]["state"] == "stale"
    assert stale[0]["stale_reasons"] == ["changed:auth.py"]


def test_exact_finding_refresh_deduplicates_and_increments_version(tmp_path, monkeypatch):
    """Re-recording one claim/anchor identity should update rather than duplicate it."""
    root = _project(tmp_path, monkeypatch)
    store = FindingStore(root)
    first = store.remember(
        claim="Refresh logic lives in auth",
        anchors=["auth.py"],
        evidence="Observed in the auth module",
        applicability="Use for refresh changes",
    )
    second = store.remember(
        claim="Refresh logic lives in auth",
        anchors=["auth.py"],
        evidence="Confirmed by the current implementation",
        applicability="Use for refresh changes",
    )

    assert second["id"] == first["id"]
    assert second["version"] == 2
    assert store.status()["total"] == 1


def test_superseded_findings_are_hidden_from_normal_recall(tmp_path, monkeypatch):
    """A replacement finding should explicitly supersede older project knowledge."""
    root = _project(tmp_path, monkeypatch)
    store = FindingStore(root)
    old = store.remember(
        claim="Refresh returns the original token",
        anchors=["auth.py"],
        evidence="Observed return statement",
        applicability="Use for refresh behavior",
    )
    new = store.remember(
        claim="Refresh behavior should be checked in auth",
        anchors=["auth.py"],
        evidence="Auth remains the source of truth",
        applicability="Use for refresh behavior",
        supersedes=[old["id"]],
    )

    current = store.recall("refresh behavior")
    all_states = store.recall("refresh behavior", include_stale=True, limit=10)

    assert [item["id"] for item in current] == [new["id"]]
    assert {item["state"] for item in all_states} == {"active", "superseded"}


def test_anchors_must_resolve_inside_repository(tmp_path, monkeypatch):
    """Knowledge must remain tied to real repository evidence."""
    root = _project(tmp_path, monkeypatch)
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repository"):
        FindingStore(root).remember(
            claim="Outside claim",
            anchors=[str(outside)],
            evidence="outside",
            applicability="never",
        )

    with pytest.raises(ValueError, match="does not exist"):
        FindingStore(root).remember(
            claim="Missing claim",
            anchors=["missing.py"],
            evidence="missing",
            applicability="never",
        )



def test_for_path_returns_only_current_verified_exact_anchors(tmp_path, monkeypatch):
    """Read avoidance should see only active verified findings for the exact file."""
    root = _project(tmp_path, monkeypatch)
    other = root / "other.py"
    other.write_text("value = 2\n", encoding="utf-8")
    store = FindingStore(root)
    verified = store.remember(
        claim="Auth owns refresh",
        anchors=["auth.py::refresh_session"],
        evidence="refresh_session is defined here",
        applicability="Use for session refresh work",
        confidence="verified",
    )
    store.remember(
        claim="Auth might own refresh",
        anchors=["auth.py"],
        evidence="partial observation",
        applicability="Use cautiously",
        confidence="probable",
    )
    store.remember(
        claim="Other module",
        anchors=["other.py"],
        evidence="other evidence",
        applicability="Use elsewhere",
        confidence="verified",
    )

    findings = store.for_path("auth.py")

    assert [item["id"] for item in findings] == [verified["id"]]


def test_for_path_excludes_stale_source(tmp_path, monkeypatch):
    """Changed files must remove their old findings from automatic path lookup."""
    root = _project(tmp_path, monkeypatch)
    store = FindingStore(root)
    store.remember(
        claim="Auth returns token",
        anchors=["auth.py"],
        evidence="current return statement",
        applicability="Use for refresh work",
    )
    (root / "auth.py").write_text(
        "def refresh_session(token):\n    return token + '-new'\n",
        encoding="utf-8",
    )

    assert store.for_path("auth.py") == []

"""Tests for universal recoverable context routing."""

from __future__ import annotations

import json

from token_saver.context_router import detect_context_kind, route_context
from token_saver.recovery import RecoveryStore


def _store(tmp_path, monkeypatch) -> RecoveryStore:
    """Create an isolated recovery store for one test."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    return RecoveryStore(tmp_path)


def test_detect_context_kind_covers_structured_payloads():
    """Routing should distinguish common high-volume context shapes."""
    assert detect_context_kind('{"items":[1,2,3]}') == "json"
    assert detect_context_kind("<html><body><button>Save</button></body></html>") == "html"
    assert detect_context_kind("a,b\n1,2\n3,4\n5,6\n") == "table"
    assert detect_context_kind("INFO start\nWARN slow\nERROR failed\nINFO end\n") == "log"
    assert detect_context_kind("src/a.py:1:x\nsrc/b.py:2:y\nsrc/c.py:3:z\nsrc/d.py:4:q\n") == "search-results"


def test_large_json_is_compacted_and_exactly_recoverable(tmp_path, monkeypatch):
    """A lossy JSON view must expose a handle that restores exact input bytes."""
    payload = {
        "items": [
            {"id": index, "name": f"entry-{index}", "detail": "noise " * 20}
            for index in range(120)
        ]
    }
    text = json.dumps(payload, indent=2)
    store = _store(tmp_path, monkeypatch)
    result = route_context(
        text,
        query="entry-77",
        recovery=store,
        min_reduction=0.05,
    )

    assert result.kind == "json"
    assert result.changed is True
    assert result.recovery_handle is not None
    assert result.output_tokens < result.original_tokens
    assert "entry-77" in result.text
    assert store.get(result.recovery_handle).payload.decode() == text


def test_log_router_keeps_failure_and_query_evidence(tmp_path, monkeypatch):
    """Log focusing should retain critical diagnostics and user-focused lines."""
    lines = [f"INFO worker={index} healthy" for index in range(220)]
    lines[130] = "WARN checkout latency high"
    lines[170] = "ERROR checkout request failed id=abc"
    text = "\n".join(lines) + "\n"
    result = route_context(
        text,
        query="checkout",
        recovery=_store(tmp_path, monkeypatch),
        max_lines=60,
        min_reduction=0.05,
    )

    assert result.kind == "log"
    assert result.changed is True
    assert "WARN checkout latency high" in result.text
    assert "ERROR checkout request failed id=abc" in result.text
    assert result.recovery_handle


def test_unprofitable_transform_keeps_original_without_handle(tmp_path, monkeypatch):
    """Small payloads should remain byte-for-byte unchanged."""
    text = '{"ok":true}'
    result = route_context(
        text,
        query="ok",
        recovery=_store(tmp_path, monkeypatch),
        min_reduction=0.20,
    )

    assert result.changed is False
    assert result.text == text
    assert result.recovery_handle is None

"""Tests for the framework-neutral Python/HTTP SDK surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from acco.sdk import AccoEngine
from acco.sdk_server import SdkApplication, SdkServerConfig


def _engine(tmp_path, monkeypatch, *, capacity=512 * 1024 * 1024):
    """Create one isolated SDK engine with private recovery state."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    return AccoEngine(root, recovery_capacity_bytes=capacity)


def test_python_sdk_context_is_recoverable(tmp_path, monkeypatch):
    """Lossy context transforms must round-trip to the exact original bytes."""
    engine = _engine(tmp_path, monkeypatch)
    original = "\n".join(
        f"progress row {index} " + "x" * 80 for index in range(240)
    )

    result = engine.optimize_context(
        original,
        query="progress",
        command="custom-agent-tool",
        max_lines=24,
        min_reduction=0.0,
    )

    assert result["changed"] is True
    assert result["output_tokens"] < result["original_tokens"]
    assert result["recovery_handle"]
    recovered = engine.recover(result["recovery_handle"])
    assert recovered["encoding"] == "utf-8"
    assert recovered["payload"] == original


def test_python_sdk_provider_request_reuses_production_transform(
    tmp_path, monkeypatch
):
    """Custom agents should get the same provider transform and recovery contract."""
    engine = _engine(tmp_path, monkeypatch)
    noisy = "\n".join(
        f"build progress {index} " + "x" * 80 for index in range(180)
    )
    body = {
        "messages": [
            {"role": "tool", "content": noisy},
            {"role": "user", "content": "diagnose the build"},
        ]
    }

    result = engine.optimize_provider_request("anthropic", body)

    assert result["metadata"]["changed"] is True
    handles = result["metadata"]["recovery_handles"]
    assert handles
    assert engine.recover(handles[0])["payload"] == noisy


def test_python_sdk_output_recovery_fails_open_on_capacity(
    tmp_path, monkeypatch
):
    """Output middleware must return the original when exact recovery cannot fit."""
    engine = _engine(tmp_path, monkeypatch, capacity=8)
    original = "\n".join(f"ordinary output line {index}" for index in range(200))

    result = engine.optimize_output(
        original,
        command="custom command",
        max_lines=20,
        keep_tail=5,
        min_reduction=0.0,
    )

    assert result["changed"] is False
    assert result["text"] == original
    assert result["recovery_handle"] is None
    assert result["output_tokens"] == result["original_tokens"]


def test_python_middleware_binds_provider_and_tool_flow(tmp_path, monkeypatch):
    """The convenience facade should map agent lifecycle calls to one engine."""
    engine = _engine(tmp_path, monkeypatch)
    middleware = engine.middleware("openai")
    body = {"messages": [{"role": "user", "content": "hello"}]}

    request = middleware.before_request(
        body,
        compress_schemas=False,
        compress_tool_results=False,
        prefix_tracking=False,
    )
    tool = middleware.after_tool_result(
        "\n".join(f"row {index} " + "x" * 50 for index in range(160)),
        query="row 99",
        command="search",
        max_lines=20,
        min_reduction=0.0,
    )

    assert request["body"] == body
    assert request["metadata"]["changed"] is False
    assert tool["changed"] is True
    assert middleware.recover(tool["recovery_handle"])["payload"].startswith(
        "row 0"
    )


def test_sdk_application_dispatches_health_context_and_recovery(
    tmp_path, monkeypatch
):
    """The HTTP bridge application should expose stable versioned primitives."""
    engine = _engine(tmp_path, monkeypatch)
    app = SdkApplication(engine)

    status, health = app.dispatch("GET", "/v1/health")
    assert status == 200
    assert health["status"] == "ok"
    assert health["root"] == str(engine.root)

    original = "\n".join(f"result {index} " + "z" * 80 for index in range(180))
    status, optimized = app.dispatch(
        "POST",
        "/v1/context/optimize",
        {
            "text": original,
            "query": "result 120",
            "command": "tool",
            "options": {"max_lines": 20, "min_reduction": 0.0},
        },
    )
    assert status == 200
    assert optimized["changed"] is True

    status, recovered = app.dispatch(
        "POST",
        "/v1/recover",
        {"handle": optimized["recovery_handle"]},
    )
    assert status == 200
    assert recovered["payload"] == original


def test_sdk_application_rejects_unknown_or_missing_recovery(
    tmp_path, monkeypatch
):
    """Transport errors should be explicit without exposing internals."""
    app = SdkApplication(_engine(tmp_path, monkeypatch))

    assert app.dispatch("GET", "/v1/nope")[0] == 405
    assert app.dispatch("POST", "/v1/nope", {}) == (404, {"error": "not_found"})
    status, missing = app.dispatch(
        "POST",
        "/v1/recover",
        {"handle": "tsr_" + "0" * 32},
    )
    assert status == 404
    assert missing["error"] == "recovery_not_found"


def test_sdk_server_defaults_to_loopback(tmp_path):
    """Non-loopback exposure must require an explicit operator override."""
    root = tmp_path / "repo"
    root.mkdir()

    safe = SdkServerConfig(root=root).validate()
    assert safe.bind == "127.0.0.1"

    with pytest.raises(ValueError, match="loopback"):
        SdkServerConfig(root=root, bind="0.0.0.0").validate()

    explicit = SdkServerConfig(
        root=root,
        bind="0.0.0.0",
        allow_non_loopback=True,
    ).validate()
    assert explicit.allow_non_loopback is True


def test_sdk_config_requires_existing_project_root(tmp_path):
    """Embedding against a nonexistent root should fail before creating state."""
    with pytest.raises(ValueError, match="existing directory"):
        AccoEngine(Path(tmp_path / "missing"))

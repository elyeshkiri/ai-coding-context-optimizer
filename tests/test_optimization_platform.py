"""Regression tests for the optimization-platform v2 surfaces."""

from __future__ import annotations

import json

import pytest

from token_saver.browser_context import compress_browser_payload
from token_saver.mcp_server.contracts import McpToolSpec
from token_saver.mcp_server.protocol import McpProtocol
from token_saver.mcp_server.tools import McpToolRegistry
from token_saver.optimizer import apply_optimization, evaluate_optimization
from token_saver.prefix_cache import observe_prefix, prefix_status
from token_saver.provider_proxy import ProviderProxyConfig, transform_request_bytes
from token_saver.provider_transform import transform_provider_request
from token_saver.recovery import RecoveryCapacityError, RecoveryStore
from token_saver.tool_schema import compress_tool_catalog


def test_recovery_store_is_content_addressed_exact_and_capacity_safe(
    tmp_path, monkeypatch
):
    """Exact bytes should dedupe, round-trip, and never evict on capacity failure."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    store = RecoveryStore(root, capacity_bytes=64)
    payload = b"exact\x00bytes\n"

    first = store.put(payload, metadata={"kind": "test"})
    second = store.put(payload, metadata={"kind": "test"})

    assert first == second
    assert first.startswith("tsr_")
    assert store.stats()["records"] == 1
    assert store.get(first).payload == payload
    assert store.get(first).access_count == 2

    with pytest.raises(RecoveryCapacityError):
        store.put(b"x" * 80)
    assert store.get(first).payload == payload


def test_tool_schema_compression_preserves_construction_contract_and_recovery(
    tmp_path, monkeypatch
):
    """Schema annotations may shrink, but property identity/defaults/constraints survive."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    long_intro = "Use this tool to inspect project context. " * 12
    catalog = [{
        "name": "inspect",
        "description": (
            long_intro
            + "The path must be absolute. Exactly one mode is required."
        ),
        "inputSchema": {
            "title": "annotation to drop",
            "type": "object",
            "properties": {
                "title": {
                    "title": "property annotation",
                    "type": "string",
                    "default": "safe",
                    "description": long_intro + "Value must be non-empty.",
                },
            },
            "required": ["title"],
        },
    }]
    store = RecoveryStore(root)

    result = compress_tool_catalog(catalog, recovery=store, min_reduction=0.0)

    assert result.changed is True
    tool = result.value[0]
    assert tool["name"] == "inspect"
    assert "must be absolute" in tool["description"]
    assert "Exactly one" in tool["description"]
    assert tool["inputSchema"]["required"] == ["title"]
    assert "title" in tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["properties"]["title"]["default"] == "safe"
    assert "title" not in tool["inputSchema"]
    assert result.recovery_handle
    recovered = json.loads(store.get(result.recovery_handle).payload)
    assert recovered == catalog


def test_browser_context_focus_is_recoverable(tmp_path, monkeypatch):
    """Focused browser context should keep the requested row and exact source recovery."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    rows = "".join(
        f"<tr><td>ORD-{index:04d}</td><td>Status {index}</td></tr>"
        for index in range(200)
    )
    html = (
        "<html><body><table>"
        + rows
        + "</table><button id='save'>Save order</button></body></html>"
    )
    store = RecoveryStore(root)

    result = compress_browser_payload(
        html,
        query="ORD-0173 save",
        max_lines=30,
        recovery=store,
    )

    assert result.changed is True
    assert "ORD-0173" in result.text
    assert "button" in result.text
    assert result.output_tokens < result.original_tokens
    assert result.recovery_handle
    assert store.get(result.recovery_handle).payload.decode() == html


def test_provider_transform_recovers_tool_output_and_tracks_stable_prefix(
    tmp_path, monkeypatch
):
    """Provider request optimization should be deterministic across latest-user turns."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    noisy = "\n".join(f"build progress {index} " + "x" * 70 for index in range(180))
    base = {
        "system": "You are a coding agent.",
        "tools": [{
            "name": "read_log",
            "description": "Read build logs. " * 40 + "Path must be absolute.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }],
        "messages": [
            {"role": "assistant", "content": "checking"},
            {"role": "tool", "content": noisy},
            {"role": "user", "content": "find the build failure"},
        ],
    }

    first = transform_provider_request(root, "anthropic", base)
    second_body = json.loads(json.dumps(base))
    second_body["messages"][-1]["content"] = "what should I fix next?"
    second = transform_provider_request(root, "anthropic", second_body)

    assert first.changed is True
    assert first.output_tokens < first.original_tokens
    assert first.recovery_handles
    recovered = RecoveryStore(root).get(first.recovery_handles[0]).payload.decode()
    assert recovered == noisy
    assert second.prefix.reused is True
    status = prefix_status(root)["providers"]["anthropic"]
    assert status["hits"] >= 1


def test_provider_transform_fails_closed_when_recovery_capacity_is_too_small(
    tmp_path, monkeypatch
):
    """A lossy transform must not ship when exact recovery cannot be stored."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    noisy = "\n".join("noise " + "x" * 80 for _ in range(150))
    body = {
        "messages": [
            {"role": "tool", "content": noisy},
            {"role": "user", "content": "diagnose"},
        ]
    }

    result = transform_provider_request(
        root,
        "generic",
        body,
        recovery_capacity_bytes=8,
    )

    assert result.changed is False
    assert result.body == body
    assert result.recovery_handles == ()


def test_prefix_tracking_ignores_only_latest_user_turn(tmp_path, monkeypatch):
    """Latest user text may change while the provider-stable prefix still hits."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    first = observe_prefix(
        root,
        "openai",
        {
            "instructions": "stable",
            "messages": [
                {"role": "assistant", "content": "prior"},
                {"role": "user", "content": "first"},
            ],
        },
    )
    second = observe_prefix(
        root,
        "openai",
        {
            "instructions": "stable",
            "messages": [
                {"role": "assistant", "content": "prior"},
                {"role": "user", "content": "second"},
            ],
        },
    )

    assert first.reused is False
    assert second.reused is True


def test_provider_proxy_security_and_json_transform(tmp_path, monkeypatch):
    """Proxy must default to loopback and transform only supported JSON bodies."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(ValueError, match="loopback"):
        ProviderProxyConfig(
            root=root,
            upstream="https://api.example.com",
            bind="0.0.0.0",
        ).validate()
    with pytest.raises(ValueError, match="plain HTTP"):
        ProviderProxyConfig(
            root=root,
            upstream="http://api.example.com",
        ).validate()

    config = ProviderProxyConfig(
        root=root,
        upstream="https://api.example.com",
    ).validate()
    passthrough = transform_request_bytes(
        config,
        b"not-json",
        content_type="application/json",
    )
    assert passthrough.body == b"not-json"
    assert passthrough.metadata["changed"] is False


def test_optimizer_auto_reverts_when_measured_tokens_per_turn_do_not_improve(
    tmp_path, monkeypatch
):
    """Closed-loop config changes should restore exact bytes on measured regression."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    config = root / ".token-saver.toml"
    original = (
        '[mcp]\nprofile = "full"\nadaptive_max_tools = 12\n'
        'compress_schemas = false\n'
    )
    config.write_text(original, encoding="utf-8")

    monkeypatch.setattr(
        "token_saver.optimizer.advisor_report",
        lambda *args, **kwargs: {"recommendations": []},
    )
    samples = iter([(1000.0, 5), (1100.0, 5)])
    monkeypatch.setattr(
        "token_saver.optimizer._mean_measured_tokens",
        lambda *args, **kwargs: next(samples),
    )

    run = apply_optimization(root, "adaptive-mcp", days=7)
    assert 'profile = "adaptive"' in config.read_text(encoding="utf-8")

    result = evaluate_optimization(root, run["id"], min_turns=5)

    assert result["decision"] == "revert"
    assert result["reverted"] is True
    assert config.read_text(encoding="utf-8") == original


def test_mcp_tools_list_schema_compression_has_recovery_metadata(
    tmp_path, monkeypatch
):
    """Compressed MCP catalogs should expose the exact original through metadata."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / ".token-saver.toml").write_text(
        '[mcp]\nprofile = "full"\ncompress_schemas = true\n',
        encoding="utf-8",
    )
    long_description = (
        "Inspect project state and return relevant evidence. " * 20
        + "The path must be absolute."
    )
    registry = McpToolRegistry([
        McpToolSpec(
            "inspect",
            long_description,
            {
                "type": "object",
                "title": "annotation",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": long_description,
                    }
                },
                "required": ["path"],
            },
            lambda context, arguments: {},
        )
    ])
    protocol = McpProtocol(tmp_path, registry=registry)

    listed = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )["result"]
    metadata = listed["_meta"]["tokenSaver"]["schemaCompression"]

    assert metadata["compressedBytes"] < metadata["originalBytes"]
    handle = metadata["recoveryHandle"]
    assert handle.startswith("tsr_")
    original_catalog = json.loads(RecoveryStore(tmp_path).get(handle).payload)
    assert original_catalog[0]["name"] == "inspect"
    assert original_catalog[0]["description"] == long_description

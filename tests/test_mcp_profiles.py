"""Tests for progressive MCP tool-schema disclosure."""

from __future__ import annotations

import json

import pytest

from token_saver.estimate import estimate_tokens
from token_saver.mcp_server.protocol import McpProtocol
from token_saver.mcp_server.tools import tool_registry_for_profile


def test_minimal_profile_contains_only_high_frequency_context_tools():
    """Minimal MCP mode should avoid advertising unrelated specialist schemas."""
    names = tool_registry_for_profile("minimal").names()

    assert names == (
        "build_context",
        "find_symbol",
        "browse_context",
        "remember_finding",
        "recall_findings",
        "route_task",
    )


def test_context_profile_includes_knowledge_but_not_output_specialists():
    """Context MCP mode should keep repository operations while dropping output tools."""
    names = set(tool_registry_for_profile("context").names())

    assert {
        "route_task",
        "recall_findings",
        "remember_finding",
        "knowledge_status",
        "semantic_index_status",
        "refresh_semantic_index",
    } <= names
    assert "output_policy" not in names
    assert "compact_output" not in names
    assert "review_diff" not in names


def test_full_profile_preserves_existing_default_surface():
    """Full MCP mode should remain backward compatible with the existing registry."""
    names = set(tool_registry_for_profile("full").names())

    assert {
        "route_task",
        "build_context",
        "compact_output",
        "review_diff",
        "recall_findings",
        "semantic_index_status",
        "refresh_semantic_index",
    } <= names


def test_unknown_profile_fails_closed():
    """A misspelled profile must not silently expose an unexpected tool surface."""
    with pytest.raises(ValueError, match="unknown MCP tool profile"):
        tool_registry_for_profile("everything")


def test_protocol_reads_profile_from_environment(tmp_path, monkeypatch):
    """Live MCP sessions should honor the bounded profile environment setting."""
    monkeypatch.setenv("TOKEN_SAVER_MCP_PROFILE", "minimal")
    protocol = McpProtocol(tmp_path)

    listed = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = tuple(tool["name"] for tool in listed["result"]["tools"])

    assert names == tool_registry_for_profile("minimal").names()



def test_minimal_profile_materially_reduces_advertised_schema_tokens():
    """Profile selection should reduce the recurring MCP tool-schema payload."""
    minimal = tool_registry_for_profile("minimal").schemas()
    full = tool_registry_for_profile("full").schemas()

    minimal_tokens = estimate_tokens(json.dumps(minimal), ".json")
    full_tokens = estimate_tokens(json.dumps(full), ".json")

    assert minimal_tokens < full_tokens
    assert len(minimal) < len(full)



def test_memory_profile_exposes_progressive_disclosure_tools_only():
    """Memory profile should expose compact project memory without unrelated output tools."""
    names = set(tool_registry_for_profile("memory").names())

    assert {"memory_index", "memory_search", "memory_get", "remember_memory"} <= names
    assert "compact_output" not in names
    assert "review_diff" not in names


def test_adaptive_profile_starts_with_bounded_core():
    """Adaptive MCP mode should advertise a small discovery-first surface."""
    names = set(tool_registry_for_profile("adaptive").names())

    assert {
        "discover_tools",
        "build_context",
        "find_symbol",
        "browse_context",
        "memory_index",
        "route_task",
    } == names
    assert len(names) < len(tool_registry_for_profile("full").names())


def test_adaptive_discovery_expands_surface_for_patch_review(tmp_path):
    """Tool discovery should activate review specialists without exposing everything."""
    protocol = McpProtocol(tmp_path, profile="adaptive")

    result = protocol.call_tool(
        "discover_tools",
        {"query": "review this patch and find impacted tests", "max_tools": 12},
    )
    payload = json.loads(result["content"][0]["text"])
    listed = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    names = {tool["name"] for tool in listed["result"]["tools"]}

    assert payload["list_changed"] is True
    assert {"build_diff_context", "review_diff", "analyze_change_impact"} <= names
    assert "compact_output" not in names
    assert len(names) <= 12


def test_adaptive_protocol_advertises_list_changed_capability(tmp_path):
    """Clients should be told that discovery may change the advertised tool list."""
    protocol = McpProtocol(tmp_path, profile="adaptive")

    initialized = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )

    assert initialized["result"]["capabilities"]["tools"]["listChanged"] is True


def test_project_config_can_select_adaptive_profile(tmp_path, monkeypatch):
    """Project config should opt into adaptive disclosure without environment mutation."""
    monkeypatch.delenv("TOKEN_SAVER_MCP_PROFILE", raising=False)
    (tmp_path / ".token-saver.toml").write_text(
        '[mcp]\nprofile = "adaptive"\nadaptive_max_tools = 10\n',
        encoding="utf-8",
    )

    protocol = McpProtocol(tmp_path)
    listed = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    names = {tool["name"] for tool in listed["result"]["tools"]}

    assert "discover_tools" in names
    assert "compact_output" not in names



def test_mcp_memory_progressive_round_trip(tmp_path, monkeypatch):
    """MCP memory tools should preserve the index-search-get disclosure contract."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "auth.py").write_text(
        "def refresh(token):\n    return token\n",
        encoding="utf-8",
    )
    protocol = McpProtocol(tmp_path, profile="memory")

    remembered = json.loads(
        protocol.call_tool(
            "remember_memory",
            {
                "claim": "Refresh tokens are handled in auth",
                "anchors": ["auth.py::refresh"],
                "evidence": "refresh is the current implementation entry point",
                "applicability": "Use for authentication changes",
                "kind": "architecture",
                "tags": ["auth", "session"],
                "importance": 4,
            },
        )["content"][0]["text"]
    )
    index = json.loads(
        protocol.call_tool(
            "memory_index",
            {"query": "authentication refresh"},
        )["content"][0]["text"]
    )
    search = json.loads(
        protocol.call_tool(
            "memory_search",
            {"query": "authentication refresh"},
        )["content"][0]["text"]
    )
    full = json.loads(
        protocol.call_tool(
            "memory_get",
            {"ids": [remembered["id"]]},
        )["content"][0]["text"]
    )

    assert index[0]["id"] == remembered["id"]
    assert "evidence" not in index[0]
    assert search[0]["id"] == remembered["id"]
    assert "snippet" in search[0]
    assert full[0]["evidence"].startswith("refresh is")
    assert full[0]["access_count"] == 1

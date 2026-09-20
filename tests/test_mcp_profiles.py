"""Tests for progressive MCP tool-schema disclosure."""

from __future__ import annotations

import pytest

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
    )


def test_context_profile_includes_knowledge_but_not_output_specialists():
    """Context MCP mode should keep repository operations while dropping output tools."""
    names = set(tool_registry_for_profile("context").names())

    assert {"recall_findings", "remember_finding", "knowledge_status"} <= names
    assert "output_policy" not in names
    assert "compact_output" not in names
    assert "review_diff" not in names


def test_full_profile_preserves_existing_default_surface():
    """Full MCP mode should remain backward compatible with the existing registry."""
    names = set(tool_registry_for_profile("full").names())

    assert {"build_context", "compact_output", "review_diff", "recall_findings"} <= names


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

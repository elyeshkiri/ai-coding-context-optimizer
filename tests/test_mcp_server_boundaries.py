"""Regression tests for MCP application, protocol, and transport boundaries."""

import io
import json

import pytest

from token_saver.mcp_server import McpProtocol, McpToolRegistry, McpToolSpec, serve_stdio
from token_saver.serve import TOOLS, call_tool


class _IndexStub:
    """Minimal index service used by custom MCP tool tests."""

    def get(self):
        """Return no repository index because the custom tool does not need one."""
        return None

    def refresh(self):
        """Return no repository index for the inert test service."""
        return None

    def status(self):
        """Return deterministic status metadata."""
        return {"stub": True}


def test_custom_tool_registry_extends_protocol_without_transport_changes(tmp_path):
    """A custom tool should plug into the protocol through the registry contract."""
    seen = []

    def echo(context, arguments):
        """Return arguments and capture the repository scope."""
        seen.append(context.root)
        return {"echo": arguments["value"]}

    registry = McpToolRegistry(
        [
            McpToolSpec(
                "echo",
                "Echo one value.",
                {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                },
                echo,
            )
        ]
    )
    protocol = McpProtocol(
        tmp_path,
        registry=registry,
        index_service=_IndexStub(),
    )

    listed = protocol.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert listed["result"]["tools"][0]["name"] == "echo"

    called = protocol.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"value": "ok"}},
        }
    )
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload == {"echo": "ok"}
    assert seen == [tmp_path]


def test_tool_registry_rejects_duplicate_names():
    """Ambiguous MCP tool names must fail during composition."""
    handler = lambda context, arguments: None
    spec = McpToolSpec("same", "same", {"type": "object"}, handler)
    with pytest.raises(ValueError, match="duplicate MCP tool registration"):
        McpToolRegistry([spec, spec])


def test_stdio_transport_depends_only_on_protocol_runtime(tmp_path):
    """The stdio adapter should read/write JSON without owning tool behavior."""
    def ping(context, arguments):
        """Return a deterministic application value."""
        return {"pong": arguments.get("value")}

    registry = McpToolRegistry(
        [
            McpToolSpec(
                "ping",
                "Ping.",
                {"type": "object", "properties": {"value": {"type": "integer"}}},
                ping,
            )
        ]
    )
    protocol = McpProtocol(
        tmp_path,
        registry=registry,
        index_service=_IndexStub(),
    )
    source = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "ping", "arguments": {"value": 3}},
            }
        )
        + "\n"
    )
    sink = io.StringIO()

    assert serve_stdio(protocol, input_stream=source, output_stream=sink) == 0
    response = json.loads(sink.getvalue())
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload == {"pong": 3}


def test_serve_facade_preserves_existing_default_tool_surface(tmp_path):
    """Legacy serve imports should still expose and execute the default MCP tools."""
    names = {tool["name"] for tool in TOOLS}
    assert {
        "browse_context",
        "output_policy",
        "build_diff_context",
        "semantic_index_status",
        "refresh_semantic_index",
    } <= names
    build_context = next(tool for tool in TOOLS if tool["name"] == "build_context")
    assert "semantic" in build_context["inputSchema"]["properties"]

    result = call_tool(
        tmp_path,
        "output_policy",
        {"mode": "terse", "max_tokens": 200},
    )
    payload = json.loads(result["content"][0]["text"])
    assert payload["mode"] == "terse"
    assert payload["max_tokens"] == 200

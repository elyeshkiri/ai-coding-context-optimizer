"""JSON-RPC protocol runtime for the Token Saver MCP server."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import McpToolContext
from .services import IndexService
from .tools import DEFAULT_TOOL_REGISTRY, McpToolRegistry

PROTOCOL_VERSION = "2025-06-18"
SERVER_VERSION = "1.0.0"


def result_content(value: object) -> dict:
    """Wrap an application value in MCP text-content form."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False),
            }
        ]
    }


class McpProtocol:
    """Translate JSON-RPC requests into injected application tool calls."""

    def __init__(
        self,
        root: Path,
        *,
        registry: McpToolRegistry | None = None,
        index_service: IndexService | None = None,
    ):
        """Compose one protocol session from repository scope and services."""
        self.root = root
        self.registry = registry or DEFAULT_TOOL_REGISTRY
        self.index_service = index_service or IndexService(root)

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call one registered tool and encode its result as MCP content."""
        context = McpToolContext(self.root, self.index_service)
        return result_content(self.registry.call(name, context, arguments))

    def handle_message(self, message: dict) -> dict | None:
        """Handle one normalized JSON-RPC request or notification."""
        method = message.get("method")
        request_id = message.get("id")

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "token-saver",
                    "version": SERVER_VERSION,
                },
            }
        elif method == "tools/list":
            result = {"tools": self.registry.schemas()}
        elif method == "tools/call":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            try:
                result = self.call_tool(
                    str(params.get("name", "")),
                    arguments,
                )
            except (ValueError, RuntimeError, OSError) as exc:
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": str(exc)}],
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "method not found",
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

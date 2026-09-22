"""Compatibility facade and composition root for the ACCO MCP server.

Application tool handlers, JSON-RPC protocol routing, and stdio transport live
under :mod:`acco.mcp_server`. Existing imports from this module remain
supported.
"""

from __future__ import annotations

from pathlib import Path

from .mcp_server.protocol import (
    PROTOCOL_VERSION as PROTOCOL_VERSION,
    McpProtocol,
    result_content,
)
from .mcp_server.services import IndexService
from .mcp_server.tools import DEFAULT_TOOL_REGISTRY
from .mcp_server.transport import serve_stdio

TOOLS = DEFAULT_TOOL_REGISTRY.schemas()


def _result(value: object) -> dict:
    """Preserve the historical private result wrapper for local callers."""
    return result_content(value)


def call_tool(
    root: Path,
    name: str,
    arguments: dict,
    service: IndexService | None = None,
) -> dict:
    """Call one MCP application tool through the default registry."""
    protocol = McpProtocol(root, index_service=service)
    return protocol.call_tool(name, arguments)


def handle_message(
    root: Path,
    message: dict,
    service: IndexService | None = None,
) -> dict | None:
    """Handle one JSON-RPC message through the default MCP protocol runtime."""
    protocol = McpProtocol(root, index_service=service)
    return protocol.handle_message(message)


def serve(root: Path) -> int:
    """Serve the ACCO MCP protocol over stdio."""
    protocol = McpProtocol(root, index_service=IndexService(root))
    return serve_stdio(protocol)

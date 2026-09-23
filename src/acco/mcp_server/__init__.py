"""Host-neutral MCP server application and transport boundaries."""

from .contracts import McpToolContext, McpToolSpec
from .protocol import PROTOCOL_VERSION, McpProtocol, result_content
from .services import IndexService
from .tools import DEFAULT_TOOL_REGISTRY, McpToolRegistry
from .transport import serve_stdio

__all__ = [
    "DEFAULT_TOOL_REGISTRY",
    "IndexService",
    "McpProtocol",
    "McpToolContext",
    "McpToolRegistry",
    "McpToolSpec",
    "PROTOCOL_VERSION",
    "result_content",
    "serve_stdio",
]

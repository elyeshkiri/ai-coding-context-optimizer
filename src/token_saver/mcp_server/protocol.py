"""JSON-RPC protocol runtime for the Token Saver MCP server."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..recovery import RecoveryStore
from ..runtime_config import settings_for
from ..tool_schema import compress_tool_catalog
from .contracts import McpToolContext
from .services import IndexService
from .tool_surface import adaptive_tool_names
from .tools import DEFAULT_TOOL_REGISTRY, McpToolRegistry, tool_registry_for_profile

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
        profile: str | None = None,
    ):
        """Compose one protocol session from repository scope and services."""
        self.root = root
        settings = settings_for(root)
        self._profile = "custom" if registry is not None else ""
        self._adaptive_max_tools = 12
        self._compress_schemas = settings.mcp_compress_schemas
        if registry is not None:
            self.registry = registry
        else:
            selected_profile = (
                profile
                or os.environ.get("TOKEN_SAVER_MCP_PROFILE")
                or settings.mcp_profile
            )
            self._profile = selected_profile.strip().lower()
            self._adaptive_max_tools = settings.mcp_adaptive_max_tools
            self.registry = tool_registry_for_profile(self._profile)
            if self._profile == "adaptive":
                initial_task = os.environ.get("TOKEN_SAVER_MCP_TASK", "").strip()
                if initial_task:
                    names = adaptive_tool_names(
                        initial_task,
                        DEFAULT_TOOL_REGISTRY.names(),
                        max_tools=self._adaptive_max_tools,
                    )
                    self.registry = DEFAULT_TOOL_REGISTRY.select(names)
        self.index_service = index_service or IndexService(root)

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call one registered tool and update adaptive disclosure when requested."""
        context = McpToolContext(self.root, self.index_service)
        effective_arguments = arguments
        if self._profile == "adaptive" and name == "discover_tools":
            effective_arguments = dict(arguments)
            requested_max = int(
                effective_arguments.get("max_tools", self._adaptive_max_tools)
            )
            effective_arguments["max_tools"] = min(
                requested_max,
                self._adaptive_max_tools,
            )
        value = self.registry.call(name, context, effective_arguments)
        if self._profile == "adaptive" and name == "discover_tools":
            if isinstance(value, dict):
                requested = value.get("tools")
                if isinstance(requested, list):
                    active = {
                        str(tool_name)
                        for tool_name in requested
                        if str(tool_name) in DEFAULT_TOOL_REGISTRY.names()
                    }
                    ordered = [
                        tool_name
                        for tool_name in DEFAULT_TOOL_REGISTRY.names()
                        if tool_name in active
                    ]
                    self.registry = DEFAULT_TOOL_REGISTRY.select(ordered)
                    value["active_tools"] = list(self.registry.names())
                    value["list_changed"] = True
        if (
            self._compress_schemas
            and name == "discover_tools"
            and isinstance(value, dict)
            and isinstance(value.get("schemas"), list)
        ):
            compressed = compress_tool_catalog(
                value["schemas"],
                recovery=RecoveryStore(self.root),
            )
            value["schemas"] = compressed.value
            value["schema_compression"] = {
                "changed": compressed.changed,
                "original_bytes": compressed.original_bytes,
                "compressed_bytes": compressed.compressed_bytes,
                "recovery_handle": compressed.recovery_handle,
            }
        return result_content(value)

    def _listed_tools(self) -> dict:
        """Return tools/list with optional recoverable schema compression."""
        schemas = self.registry.schemas()
        if not self._compress_schemas:
            return {"tools": schemas}
        compressed = compress_tool_catalog(
            schemas,
            recovery=RecoveryStore(self.root),
        )
        result = {"tools": compressed.value}
        if compressed.changed:
            result["_meta"] = {
                "tokenSaver": {
                    "schemaCompression": {
                        "originalBytes": compressed.original_bytes,
                        "compressedBytes": compressed.compressed_bytes,
                        "recoveryHandle": compressed.recovery_handle,
                    }
                }
            }
        return result

    def handle_message(self, message: dict) -> dict | None:
        """Handle one normalized JSON-RPC request or notification."""
        method = message.get("method")
        request_id = message.get("id")

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": self._profile == "adaptive"}
                },
                "serverInfo": {
                    "name": "token-saver",
                    "version": SERVER_VERSION,
                },
            }
        elif method == "tools/list":
            result = self._listed_tools()
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

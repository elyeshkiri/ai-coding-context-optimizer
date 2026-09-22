"""Stdio transport adapter for the host-neutral MCP protocol runtime."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from .protocol import McpProtocol


def _parse_error(exc: Exception) -> dict:
    """Return a JSON-RPC parse-error response for malformed transport input."""
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": str(exc)},
    }


def serve_stdio(
    protocol: McpProtocol,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Serve newline-delimited JSON-RPC messages over injected text streams."""
    source = input_stream or sys.stdin
    sink = output_stream or sys.stdout
    for line in source:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise TypeError("JSON-RPC message must be an object")
            response = protocol.handle_message(message)
        except (ValueError, TypeError) as exc:
            response = _parse_error(exc)
        if response is not None:
            sink.write(json.dumps(response, separators=(",", ":")) + "\n")
            sink.flush()
    return 0

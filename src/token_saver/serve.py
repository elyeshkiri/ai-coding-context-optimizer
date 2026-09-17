"""Small stdio MCP server exposing Token Saver's context compiler."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .feedback import record_feedback
from .impact import analyze_impact
from .pack import build_context_pack
from .repo_index import build_index

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "build_context",
        "description": "Build a task-aware source context pack under a hard token budget.",
        "inputSchema": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"}, "max_tokens": {"type": "integer", "minimum": 1},
            "target_symbol": {"type": "string"},
        }},
    },
    {
        "name": "find_symbol",
        "description": "Find exact or partial symbol definitions with source ranges.",
        "inputSchema": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string"},
        }},
    },
    {
        "name": "analyze_change_impact",
        "description": "Find callers, dependents, and related tests for a file or symbol.",
        "inputSchema": {"type": "object", "required": ["target"], "properties": {
            "target": {"type": "string"},
        }},
    },
    {
        "name": "report_context_feedback",
        "description": "Record whether an included file was useful for future local ranking.",
        "inputSchema": {"type": "object", "required": ["path", "useful"], "properties": {
            "path": {"type": "string"}, "useful": {"type": "boolean"},
        }},
    },
]


def _result(value) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def call_tool(root: Path, name: str, arguments: dict) -> dict:
    if name == "build_context":
        pack = build_context_pack(
            root, str(arguments.get("query", "")),
            max_tokens=int(arguments.get("max_tokens", 6000)),
            target_symbol=arguments.get("target_symbol"),
        )
        return _result({
            "text": pack.text, "estimated_tokens": pack.estimated_tokens,
            "selected_files": pack.selected_files,
            "selected_symbols": pack.selected_symbols, "redactions": pack.redactions,
        })
    if name == "find_symbol":
        index = build_index(root)
        found = [
            {"path": rel, "name": symbol.name, "kind": symbol.kind,
             "start_line": symbol.start_line, "end_line": symbol.end_line,
             "signature": symbol.signature, "parent": symbol.parent}
            for rel, symbol in index.find_symbols(str(arguments.get("name", "")))
        ]
        return _result(found)
    if name == "analyze_change_impact":
        return _result(analyze_impact(root, str(arguments.get("target", ""))).to_dict())
    if name == "report_context_feedback":
        scores = record_feedback(
            root, str(arguments.get("path", "")), useful=bool(arguments.get("useful"))
        )
        return _result({"scores": scores})
    raise ValueError(f"unknown tool: {name}")


def handle_message(root: Path, message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "token-saver", "version": "0.9.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(root, str(params.get("name", "")), params.get("arguments") or {})
        except (ValueError, RuntimeError, OSError) as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(root: Path) -> int:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle_message(root, message)
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        except (ValueError, TypeError) as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": str(exc),
            }}), flush=True)
    return 0


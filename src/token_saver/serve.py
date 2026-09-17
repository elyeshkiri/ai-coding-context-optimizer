"""Small stdio MCP server exposing Token Saver's context compiler."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass
import time

from .feedback import record_feedback
from .impact import analyze_impact
from .pack import build_context_pack
from .patch_context import build_diff_context, review_patch
from .output_saver import build_output_policy, compact_output
from .repo_index import RepositoryIndex, build_index

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
    {
        "name": "index_status",
        "description": "Report persistent repository index size, reuse, and refresh time.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "refresh_index",
        "description": "Incrementally refresh the persistent repository index.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "build_diff_context",
        "description": "Build context around the current Git patch and its impact closure.",
        "inputSchema": {"type": "object", "properties": {
            "base": {"type": "string"}, "staged": {"type": "boolean"},
            "max_tokens": {"type": "integer", "minimum": 1},
        }},
    },
    {
        "name": "review_diff",
        "description": "Report changed symbols, impact, API changes, and test coverage signals.",
        "inputSchema": {"type": "object", "properties": {
            "base": {"type": "string"}, "staged": {"type": "boolean"},
        }},
    },
    {
        "name": "output_policy",
        "description": "Return a generation-time response policy for reducing output tokens.",
        "inputSchema": {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["terse", "normal", "detailed"]},
            "max_tokens": {"type": "integer", "minimum": 1},
        }},
    },
    {
        "name": "compact_output",
        "description": "Safely compact generated prose while preserving fenced code/diffs exactly.",
        "inputSchema": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string"},
            "mode": {"type": "string", "enum": ["terse", "normal", "detailed"]},
            "max_tokens": {"type": "integer", "minimum": 1},
            "enforce_budget": {"type": "boolean"},
        }},
    },
]


@dataclass
class IndexService:
    root: Path
    index: RepositoryIndex | None = None
    refreshed_at: float | None = None

    def refresh(self):
        self.index = build_index(self.root)
        self.refreshed_at = time.time()
        return self.index

    def get(self):
        return self.index or self.refresh()

    def status(self) -> dict:
        index = self.get()
        return {
            "files": len(index.records), "reparsed": index.reparsed,
            "reused": index.reused, "refreshed_at": self.refreshed_at,
            "index_version": 3,
        }


def _result(value) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def call_tool(
    root: Path, name: str, arguments: dict, service: IndexService | None = None,
) -> dict:
    service = service or IndexService(root)
    if name == "build_context":
        pack = build_context_pack(
            root, str(arguments.get("query", "")),
            max_tokens=int(arguments.get("max_tokens", 6000)),
            target_symbol=arguments.get("target_symbol"),
            index=service.get(),
        )
        return _result({
            "text": pack.text, "estimated_tokens": pack.estimated_tokens,
            "selected_files": pack.selected_files,
            "selected_symbols": pack.selected_symbols, "redactions": pack.redactions,
            "closure_files": pack.closure_files,
        })
    if name == "find_symbol":
        index = service.get()
        found = [
            {"path": rel, "name": symbol.name, "kind": symbol.kind,
             "start_line": symbol.start_line, "end_line": symbol.end_line,
             "signature": symbol.signature, "parent": symbol.parent}
            for rel, symbol in index.find_symbols(str(arguments.get("name", "")))
        ]
        return _result(found)
    if name == "analyze_change_impact":
        return _result(analyze_impact(
            root, str(arguments.get("target", "")), index=service.get()
        ).to_dict())
    if name == "report_context_feedback":
        scores = record_feedback(
            root, str(arguments.get("path", "")), useful=bool(arguments.get("useful"))
        )
        return _result({"scores": scores})
    if name == "index_status":
        return _result(service.status())
    if name == "refresh_index":
        service.refresh()
        return _result(service.status())
    if name == "build_diff_context":
        return _result(build_diff_context(
            root, base=str(arguments.get("base", "HEAD")),
            staged=bool(arguments.get("staged", False)),
            max_tokens=int(arguments.get("max_tokens", 6000)),
        ))
    if name == "review_diff":
        return _result(review_patch(
            root, base=str(arguments.get("base", "HEAD")),
            staged=bool(arguments.get("staged", False)),
        ))
    if name == "output_policy":
        policy = build_output_policy(
            str(arguments.get("mode", "normal")),
            int(arguments["max_tokens"]) if "max_tokens" in arguments else None,
        )
        return _result(policy.to_dict())
    if name == "compact_output":
        result = compact_output(
            str(arguments.get("text", "")),
            mode=str(arguments.get("mode", "normal")),
            max_tokens=int(arguments["max_tokens"]) if "max_tokens" in arguments else None,
            enforce_budget=bool(arguments.get("enforce_budget", False)),
        )
        return _result(result.to_dict())
    raise ValueError(f"unknown tool: {name}")


def handle_message(
    root: Path, message: dict, service: IndexService | None = None,
) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "token-saver", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(
                root, str(params.get("name", "")), params.get("arguments") or {}, service
            )
        except (ValueError, RuntimeError, OSError) as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(root: Path) -> int:
    service = IndexService(root)
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle_message(root, message, service)
            if response is not None:
                print(json.dumps(response, separators=(",", ":")), flush=True)
        except (ValueError, TypeError) as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": str(exc),
            }}), flush=True)
    return 0

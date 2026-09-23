"""Measure what MCP servers actually cost in tool-schema tokens.

`audit` used to list server names and tell you to run `/context`. That is not a
measurement. An MCP server's tool schemas are sent with the request, so their
size is a real, recurring cost — and it is knowable: the server will tell you if
you ask it.

Probing **launches the server process**, so it is opt-in and never runs by
default. Servers are spoken to over stdio with newline-delimited JSON-RPC, given
a hard timeout, and killed afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .estimate import estimate_tokens

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = 15


@dataclass
class ServerCost:
    """Represent server cost state and behavior."""
    name: str
    tools: int | None = None
    tokens: int | None = None
    status: str = "not probed"

    @property
    def measured(self) -> bool:
        """Return measured for server cost."""
        return self.tokens is not None


def load_servers(root: Path) -> dict[str, dict]:
    """Merge the MCP server definitions a project declares."""
    servers: dict[str, dict] = {}
    for config in (root / ".mcp.json", root / ".claude" / "mcp.json"):
        if not config.is_file():
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found = data.get("mcpServers")
        if isinstance(found, dict):
            for name, spec in found.items():
                if isinstance(spec, dict):
                    servers[name] = spec
    return servers


def _handshake_payload() -> str:
    """initialize + initialized + tools/list, written in one go.

    Sending all three without waiting avoids a read deadlock against servers
    that buffer; every compliant server answers the id=2 request regardless of
    how the frames were batched.
    """
    messages = [
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "acco", "version": "0.2.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    return "".join(json.dumps(m) + "\n" for m in messages)


def probe(name: str, spec: dict, timeout: int = DEFAULT_TIMEOUT,
          cwd: Path | None = None) -> ServerCost:
    """Ask one stdio MCP server for its tool list and measure the schemas.

    `cwd` should be the project root: server commands in .mcp.json are written
    relative to the project, not to wherever acco was invoked from.
    """
    cost = ServerCost(name=name)
    if spec.get("type") in {"http", "sse"} or spec.get("url"):
        cost.status = "remote server — not probed (needs auth)"
        return cost
    command = spec.get("command")
    if not command:
        cost.status = "no command in config"
        return cost

    argv = [command, *(spec.get("args") or [])]
    env = dict(spec.get("env") or {})
    merged = {**os.environ, **{k: str(v) for k, v in env.items()}}
    try:
        proc = subprocess.run(
            argv,
            input=_handshake_payload(),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except FileNotFoundError:
        cost.status = f"command not found: {command}"
        return cost
    except subprocess.TimeoutExpired:
        cost.status = f"timed out after {timeout}s"
        return cost
    except (OSError, subprocess.SubprocessError) as exc:
        cost.status = f"failed: {type(exc).__name__}"
        return cost

    tools = _extract_tools(proc.stdout)
    if tools is None:
        cost.status = "no tools/list response"
        return cost
    cost.tools = len(tools)
    cost.tokens = estimate_tokens(json.dumps(tools), ".json")
    cost.status = "measured"
    return cost


def _extract_tools(stdout: str) -> list | None:
    """Extract tools."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        result = message.get("result")
        if message.get("id") == 2 and isinstance(result, dict):
            tools = result.get("tools")
            if isinstance(tools, list):
                return tools
    return None


def probe_all(root: Path, timeout: int = DEFAULT_TIMEOUT) -> list[ServerCost]:
    """Handle probe all."""
    return [
        probe(name, spec, timeout, cwd=root)
        for name, spec in sorted(load_servers(root).items())
    ]

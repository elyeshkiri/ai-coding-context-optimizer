"""Contracts shared by MCP tool registries and protocol adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class IndexServiceContract(Protocol):
    """Expose repository-index lifecycle operations required by MCP tools."""

    def get(self):
        """Return the current repository index, building it when necessary."""
        ...

    def refresh(self):
        """Refresh and return the repository index."""
        ...

    def status(self) -> dict:
        """Return index lifecycle and size metadata."""
        ...


@dataclass(frozen=True)
class McpToolContext:
    """Provide application services and repository scope to one MCP tool call."""

    root: Path
    index: IndexServiceContract


McpToolHandler = Callable[[McpToolContext, dict], object]


@dataclass(frozen=True)
class McpToolSpec:
    """Describe one MCP tool and bind it to its application handler."""

    name: str
    description: str
    input_schema: dict
    handler: McpToolHandler

    def to_schema(self) -> dict:
        """Return the MCP tools/list representation without implementation details."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

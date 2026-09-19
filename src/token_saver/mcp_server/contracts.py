"""Contracts shared by MCP tool registries and protocol adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RepositoryContextServiceContract(Protocol):
    """Expose repository application operations required by MCP tools."""

    def get(self):
        """Return the current repository index, building it when necessary."""
        ...

    def refresh(self):
        """Refresh and return the repository index."""
        ...

    def status(self) -> dict:
        """Return index lifecycle and size metadata."""
        ...

    def build_context(self, query: str, **kwargs):
        """Build a task-aware context pack."""
        ...

    def browse(self, query: str, **kwargs) -> dict:
        """Return ranked repository context candidates."""
        ...

    def find_symbols(self, name: str) -> list[dict]:
        """Return normalized symbol-definition records."""
        ...

    def impact(self, target: str):
        """Return change-impact analysis for a target."""
        ...

    def feedback(self, path: str, *, useful: bool) -> dict[str, float]:
        """Record local ranking feedback."""
        ...


IndexServiceContract = RepositoryContextServiceContract


@dataclass(frozen=True)
class McpToolContext:
    """Provide application services and repository scope to one MCP tool call."""

    root: Path
    index: RepositoryContextServiceContract

    @property
    def repository(self) -> RepositoryContextServiceContract:
        """Return the shared repository application service."""
        return self.index


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

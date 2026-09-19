"""Concrete application services used by the MCP server composition root."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..repo_index import RepositoryIndex, build_index


@dataclass
class IndexService:
    """Cache and incrementally refresh one repository index for a server session."""

    root: Path
    index: RepositoryIndex | None = None
    refreshed_at: float | None = None

    def refresh(self) -> RepositoryIndex:
        """Refresh and return the repository index."""
        self.index = build_index(self.root)
        self.refreshed_at = time.time()
        return self.index

    def get(self) -> RepositoryIndex:
        """Return the current index, creating it lazily on first use."""
        return self.index or self.refresh()

    def status(self) -> dict:
        """Return index size, reuse, refresh, and schema-version metadata."""
        index = self.get()
        return {
            "files": len(index.records),
            "reparsed": index.reparsed,
            "reused": index.reused,
            "refreshed_at": self.refreshed_at,
            "index_version": 3,
        }

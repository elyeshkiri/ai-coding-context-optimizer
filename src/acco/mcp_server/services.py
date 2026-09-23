"""Concrete application services used by the MCP server composition root."""

from ..repository_service import RepositoryContextService


class IndexService(RepositoryContextService):
    """Backward-compatible MCP name for the shared repository context service."""

    def status(self) -> dict:
        """Preserve the historical MCP index-status schema version field."""
        result = super().status()
        result["index_version"] = 3
        return result

"""Concrete application services used by the MCP server composition root."""

from ..repository_service import RepositoryContextService


class IndexService(RepositoryContextService):
    """Backward-compatible MCP name for the shared repository context service."""

"""Application service for repository retrieval, graph, and context operations.

This module is the shared orchestration boundary for CLI, MCP, and future host
adapters. Low-level ranking/index modules remain independently usable, but
integration surfaces should depend on :class:`RepositoryContextService`
instead of composing them directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .context_browser import browse_context
from .feedback import record_feedback
from .impact import ImpactReport, analyze_impact
from .knowledge import FindingStore
from .pack import ContextPack, build_context_pack, rank_files
from .packing.observability import explain_ranked_files
from .packing.ranking_stages import RankingStageRegistry
from .repo_index import INDEX_VERSION, RepositoryIndex, build_index
from .semantic_retrieval import SemanticVectorIndex, semantic_status
from .semantic_ts import enrich_index_with_typescript
from .retrieval_cache import status as retrieval_cache_status
from .runtime_config import settings_for


@dataclass
class RepositoryContextService:
    """Coordinate repository indexing and context-oriented application use cases."""

    root: Path
    index: RepositoryIndex | None = None
    refreshed_at: float | None = None
    use_gitignore: bool = True
    persist_index: bool = True
    retrieval_cache_enabled: bool | None = None
    retrieval_cache_max_entries: int | None = None

    def __post_init__(self) -> None:
        """Normalize repository scope once at the application boundary."""
        self.root = self.root.resolve()
        settings = settings_for(self.root)
        if self.retrieval_cache_enabled is None:
            self.retrieval_cache_enabled = settings.retrieval_cache
        if self.retrieval_cache_max_entries is None:
            self.retrieval_cache_max_entries = settings.retrieval_cache_max_entries

    def refresh(self) -> RepositoryIndex:
        """Rebuild the repository index using this service's persistence policy."""
        self.index = build_index(
            self.root,
            use_gitignore=self.use_gitignore,
            persist=self.persist_index,
        )
        self.refreshed_at = time.time()
        return self.index

    def get(self) -> RepositoryIndex:
        """Return the current repository index, creating it lazily if necessary."""
        return self.index or self.refresh()

    def status(self) -> dict:
        """Return repository-index lifecycle and size metadata."""
        index = self.get()
        return {
            "files": len(index.records),
            "reparsed": index.reparsed,
            "reused": index.reused,
            "refreshed_at": self.refreshed_at,
            "index_version": INDEX_VERSION,
            "retrieval_cache": retrieval_cache_status(self.root),
            "semantic_index": semantic_status(self.root),
        }

    def sync_semantic_index(self) -> dict:
        """Build or incrementally refresh persistent chunk-level semantic vectors."""
        return SemanticVectorIndex(self.root, self.get()).sync().to_dict()

    def semantic_index_status(self) -> dict:
        """Report persistent semantic-index state without loading the ML model."""
        return semantic_status(self.root)

    def enrich_typescript(
        self,
        *,
        enabled: bool | None = None,
        strict: bool = False,
        timeout: float = 20.0,
    ) -> int:
        """Overlay compiler-resolved TypeScript edges onto the shared index."""
        return enrich_index_with_typescript(
            self.get(),
            enabled=enabled,
            strict=strict,
            timeout=timeout,
        )

    def build_context(
        self,
        query: str,
        *,
        max_tokens: int = 6000,
        max_files: int = 12,
        context_lines: int = 6,
        changed_boost: bool = True,
        graph_hops: int = 1,
        duplicate_threshold: float = 0.92,
        session: str | None = None,
        embeddings: bool = False,
        target_symbol: str | None = None,
        feedback_boost: bool = True,
        closure_max_items: int = 20,
        changed_files: set[str] | None = None,
        priority_files: set[str] | None = None,
        exclude_files: set[str] | None = None,
        restrict_files: set[str] | None = None,
        adaptive_budget: bool = True,
        stage_registry: RankingStageRegistry | None = None,
    ) -> ContextPack:
        """Build a task-aware context pack using the service's shared index."""
        return build_context_pack(
            self.root,
            query,
            max_tokens=max_tokens,
            max_files=max_files,
            context_lines=context_lines,
            use_gitignore=self.use_gitignore,
            changed_boost=changed_boost,
            graph_hops=graph_hops,
            duplicate_threshold=duplicate_threshold,
            session=session,
            embeddings=embeddings,
            persist_index=self.persist_index,
            target_symbol=target_symbol,
            feedback_boost=feedback_boost,
            closure_max_items=closure_max_items,
            index=self.get(),
            changed_files=changed_files,
            priority_files=priority_files,
            exclude_files=exclude_files,
            restrict_files=restrict_files,
            adaptive_budget=adaptive_budget,
            stage_registry=stage_registry,
            cache_enabled=bool(self.retrieval_cache_enabled),
            cache_max_entries=int(self.retrieval_cache_max_entries or 64),
        )

    def explain_ranking(
        self,
        query: str,
        *,
        max_files: int = 8,
        changed_boost: bool = True,
        graph_hops: int = 1,
        session: str | None = None,
        embeddings: bool = False,
        feedback_boost: bool = True,
        closure_max_items: int = 20,
        priority_files: set[str] | None = None,
        exclude_files: set[str] | None = None,
        restrict_files: set[str] | None = None,
        stage_registry: RankingStageRegistry | None = None,
        include_paths: set[str] | None = None,
    ) -> dict:
        """Explain file-ranking score contributions for one repository query."""
        ranked = rank_files(
            self.root,
            query,
            use_gitignore=self.use_gitignore,
            changed_boost=changed_boost,
            index=self.get(),
            graph_hops=graph_hops,
            session=session,
            embeddings=embeddings,
            feedback_boost=feedback_boost,
            closure_max_items=closure_max_items,
            priority_files=priority_files,
            exclude_files=exclude_files,
            restrict_files=restrict_files,
            stage_registry=stage_registry,
            trace_scores=True,
        )
        return explain_ranked_files(
            query,
            ranked,
            max_files=max_files,
            include_paths=include_paths,
        )

    def browse(
        self,
        query: str,
        *,
        max_files: int = 8,
        preview_tokens: int = 350,
        detail_tokens: int = 1200,
        changed_boost: bool = True,
    ) -> dict:
        """Inspect ranked repository candidates using the shared retrieval index."""
        return browse_context(
            self.root,
            query,
            max_files=max_files,
            preview_tokens=preview_tokens,
            detail_tokens=detail_tokens,
            changed_boost=changed_boost,
            index=self.get(),
        )

    def find_symbols(self, name: str) -> list[dict]:
        """Return normalized symbol-definition records for one search term."""
        return [
            {
                "path": rel,
                "name": symbol.name,
                "kind": symbol.kind,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "signature": symbol.signature,
                "parent": symbol.parent,
            }
            for rel, symbol in self.get().find_symbols(name)
        ]

    def impact(self, target: str) -> ImpactReport:
        """Analyze callers, dependents, and related tests for a target."""
        return analyze_impact(self.root, target, index=self.get())

    def feedback(self, path: str, *, useful: bool) -> dict[str, int]:
        """Record local ranking feedback for one repository-relative file."""
        return record_feedback(self.root, path, useful=useful)

    def remember_finding(
        self,
        *,
        claim: str,
        anchors: list[str],
        evidence: str,
        applicability: str,
        confidence: str = "verified",
        invalidators: list[str] | None = None,
        supersedes: list[str] | None = None,
        source: str = "manual",
    ) -> dict:
        """Persist one explicit evidence-backed project finding."""
        return FindingStore(self.root).remember(
            claim=claim,
            anchors=anchors,
            evidence=evidence,
            applicability=applicability,
            confidence=confidence,
            invalidators=invalidators,
            supersedes=supersedes,
            source=source,
        )

    def recall_findings(
        self,
        query: str,
        *,
        limit: int = 5,
        include_stale: bool = False,
    ) -> list[dict]:
        """Recall current project findings relevant to a task query."""
        return FindingStore(self.root).recall(
            query,
            limit=limit,
            include_stale=include_stale,
        )

    def knowledge_status(self) -> dict:
        """Return project-knowledge counts without exposing finding contents."""
        return FindingStore(self.root).status()

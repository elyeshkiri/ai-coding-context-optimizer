"""Extension contracts and registry for post-score ranking stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import RankedFile
from .file_scoring import _FileRankingScope


@dataclass(frozen=True)
class RankingStageOptions:
    """Configuration shared by post-score ranking stages."""

    priority_files: frozenset[str] | None
    seed_limit: int
    graph_hops: int
    closure_max_items: int
    embeddings: bool


@dataclass(frozen=True)
class RankingStageContext:
    """Provide immutable ranking scope and stage configuration."""

    scope: _FileRankingScope
    options: RankingStageOptions


class RankingStage(Protocol):
    """Contract for one post-score ranking extension."""

    name: str
    order: int

    def enabled(self, context: RankingStageContext) -> bool:
        """Return whether this stage should run for the current request."""
        ...

    def apply(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Mutate ranking evidence/scores in place without final reordering."""
        ...


class RankingStageRegistry:
    """Validate and run post-score ranking extensions in deterministic order."""

    def __init__(self, stages: list[RankingStage] | tuple[RankingStage, ...]):
        """Register stages and reject ambiguous names or execution orders."""
        by_name: dict[str, RankingStage] = {}
        by_order: dict[int, RankingStage] = {}
        for stage in stages:
            if not stage.name:
                raise ValueError("ranking stage name must be non-empty")
            if stage.name in by_name:
                raise ValueError(f"duplicate ranking stage registration: {stage.name}")
            if stage.order in by_order:
                other = by_order[stage.order]
                raise ValueError(
                    "duplicate ranking stage order "
                    f"{stage.order}: {other.name}, {stage.name}"
                )
            by_name[stage.name] = stage
            by_order[stage.order] = stage
        self._stages = tuple(
            stage for _order, stage in sorted(by_order.items())
        )

    def names(self) -> tuple[str, ...]:
        """Return registered stage names in execution order."""
        return tuple(stage.name for stage in self._stages)

    def run(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Run enabled stages in deterministic order without implicit sorting."""
        for stage in self._stages:
            if stage.enabled(context):
                stage.apply(context, ranked)

    def extend(self, *stages: RankingStage) -> "RankingStageRegistry":
        """Return a new registry containing existing stages plus extensions."""
        return RankingStageRegistry((*self._stages, *stages))

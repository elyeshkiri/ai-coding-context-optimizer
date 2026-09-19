"""Internal stages and extension contracts for task-aware context packing."""

from .contracts import ContextPack, RankedFile
from .ranking_defaults import DEFAULT_RANKING_STAGE_REGISTRY
from .ranking_stages import (
    RankingStage,
    RankingStageContext,
    RankingStageOptions,
    RankingStageRegistry,
)

__all__ = [
    "ContextPack",
    "DEFAULT_RANKING_STAGE_REGISTRY",
    "RankedFile",
    "RankingStage",
    "RankingStageContext",
    "RankingStageOptions",
    "RankingStageRegistry",
]

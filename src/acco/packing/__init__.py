"""Internal stages and extension contracts for task-aware context packing."""

from .contracts import ContextPack, RankedFile, RankingScoreEvent
from .observability import explain_ranked_files
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
    "RankingScoreEvent",
    "explain_ranked_files",
    "RankingStage",
    "RankingStageContext",
    "RankingStageOptions",
    "RankingStageRegistry",
]

"""Default ranking-stage composition preserving the validated baseline."""

from .graph_rerank import EmbeddingRerankStage, GraphClosureStage
from .ranking_stages import RankingStageRegistry

DEFAULT_RANKING_STAGE_REGISTRY = RankingStageRegistry(
    (
        GraphClosureStage(),
        EmbeddingRerankStage(),
    )
)

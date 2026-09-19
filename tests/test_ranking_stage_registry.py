"""Tests for pluggable post-score ranking stages and registry validation."""

from __future__ import annotations

import textwrap

import pytest

from token_saver.pack import rank_files
from token_saver.repository_service import RepositoryContextService
from token_saver.packing import (
    DEFAULT_RANKING_STAGE_REGISTRY,
    RankingStageContext,
    RankingStageOptions,
    RankingStageRegistry,
)
from token_saver.packing.contracts import RankedFile


class _RecordingStage:
    """Small deterministic stage used to exercise registry behavior."""

    def __init__(self, name: str, order: int, seen: list[str], *, enabled: bool = True):
        """Capture stage metadata and the shared execution log."""
        self.name = name
        self.order = order
        self.seen = seen
        self.is_enabled = enabled

    def enabled(self, context: RankingStageContext) -> bool:
        """Return the configured stage gate."""
        del context
        return self.is_enabled

    def apply(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Record execution without changing ranking evidence."""
        del context, ranked
        self.seen.append(self.name)


class _BoostLastStage:
    """Boost the current final candidate to prove final sorting stays centralized."""

    name = "boost-last"
    order = 150

    def enabled(self, context: RankingStageContext) -> bool:
        """Run for every request."""
        del context
        return True

    def apply(
        self,
        context: RankingStageContext,
        ranked: list[RankedFile],
    ) -> None:
        """Give the current last item enough score to become first."""
        del context
        ranked[-1].score += 10_000.0
        ranked[-1].reasons.append("custom:boost-last")


def _context() -> RankingStageContext:
    """Return an inert stage context for registry-only tests."""
    return RankingStageContext(
        scope=None,  # type: ignore[arg-type]
        options=RankingStageOptions(
            priority_files=None,
            seed_limit=6,
            graph_hops=1,
            closure_max_items=20,
            embeddings=False,
        ),
    )


def _repo(tmp_path):
    """Create a small repository with two deterministic ranking candidates."""
    (tmp_path / "primary.py").write_text(
        textwrap.dedent(
            """
            def refresh_session(token):
                return token
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "secondary.py").write_text(
        textwrap.dedent(
            """
            def invoice_total(value):
                return value
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_registry_runs_enabled_stages_in_declared_order():
    """Registration order must not override explicit stage order."""
    seen: list[str] = []
    registry = RankingStageRegistry(
        (
            _RecordingStage("late", 200, seen),
            _RecordingStage("disabled", 150, seen, enabled=False),
            _RecordingStage("early", 100, seen),
        )
    )

    registry.run(_context(), [])

    assert registry.names() == ("early", "disabled", "late")
    assert seen == ["early", "late"]


def test_registry_rejects_duplicate_names():
    """Duplicate stage names must fail during composition."""
    seen: list[str] = []
    with pytest.raises(ValueError, match="duplicate ranking stage registration"):
        RankingStageRegistry(
            (
                _RecordingStage("same", 100, seen),
                _RecordingStage("same", 200, seen),
            )
        )


def test_registry_rejects_duplicate_execution_orders():
    """Equal stage orders are ambiguous and must fail during composition."""
    seen: list[str] = []
    with pytest.raises(ValueError, match="duplicate ranking stage order"):
        RankingStageRegistry(
            (
                _RecordingStage("one", 100, seen),
                _RecordingStage("two", 100, seen),
            )
        )


def test_default_registry_preserves_graph_then_embedding_order():
    """The validated baseline must retain graph evidence before embeddings."""
    assert DEFAULT_RANKING_STAGE_REGISTRY.names() == (
        "graph-closure",
        "embeddings",
    )


def test_default_registry_can_be_extended_without_mutation():
    """Custom extensions should compose into a new registry."""
    seen: list[str] = []
    custom = _RecordingStage("custom", 300, seen)

    extended = DEFAULT_RANKING_STAGE_REGISTRY.extend(custom)

    assert DEFAULT_RANKING_STAGE_REGISTRY.names() == (
        "graph-closure",
        "embeddings",
    )
    assert extended.names() == (
        "graph-closure",
        "embeddings",
        "custom",
    )


def test_custom_registry_runs_before_existing_final_sort(tmp_path):
    """A custom score mutation should participate in rank_files' final ordering."""
    root = _repo(tmp_path)
    baseline = rank_files(
        root,
        "refresh session token",
        changed_boost=False,
        feedback_boost=False,
        stage_registry=RankingStageRegistry(()),
    )
    assert len(baseline) == 2
    original_last = baseline[-1].rel

    ranked = rank_files(
        root,
        "refresh session token",
        changed_boost=False,
        feedback_boost=False,
        stage_registry=RankingStageRegistry((_BoostLastStage(),)),
    )

    assert ranked[0].rel == original_last
    assert "custom:boost-last" in ranked[0].reasons


def test_repository_service_forwards_custom_stage_registry(tmp_path):
    """Application-service context builds should honor injected ranking stages."""
    root = _repo(tmp_path)
    service = RepositoryContextService(root, persist_index=False)
    registry = RankingStageRegistry((_BoostLastStage(),))

    pack = service.build_context(
        "refresh session token",
        max_tokens=800,
        changed_boost=False,
        feedback_boost=False,
        adaptive_budget=False,
        stage_registry=registry,
    )

    assert any(
        "custom:boost-last" in item.reasons
        for item in pack.ranked
    )

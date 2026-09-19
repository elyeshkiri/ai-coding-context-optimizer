"""Tests for structured ranking score traces and explanation surfaces."""

from __future__ import annotations

import json
import math
import textwrap

import pytest

from token_saver.command_handlers.context import ranking_explain_main
from token_saver.pack import rank_files
from token_saver.packing import RankingStageRegistry
from token_saver.packing.ranking_stages import RankingStageContext
from token_saver.repository_service import RepositoryContextService
from token_saver.serve import TOOLS, call_tool


class _BoostStage:
    """Custom reranker used to verify automatic stage instrumentation."""

    name = "test-boost"
    order = 100

    def enabled(self, context: RankingStageContext) -> bool:
        """Enable the synthetic stage for every request."""
        del context
        return True

    def apply(self, context: RankingStageContext, ranked) -> None:
        """Apply a fixed score delta and evidence to every candidate."""
        del context
        for item in ranked:
            item.score += 3.5
            item.reasons.append("custom:test-boost")


class _ReorderStage:
    """Invalid reranker used to verify candidate-list integrity protection."""

    name = "reorder"
    order = 100

    def enabled(self, context: RankingStageContext) -> bool:
        """Enable the invalid stage for every request."""
        del context
        return True

    def apply(self, context: RankingStageContext, ranked) -> None:
        """Reverse candidates, which the registry contract forbids."""
        del context
        ranked.reverse()


def _repo(tmp_path):
    """Create a deterministic repository for ranking-observability tests."""
    (tmp_path / "auth.py").write_text(
        textwrap.dedent(
            """
            class SessionManager:
                def refresh_session(self, token):
                    return token
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "billing.py").write_text(
        textwrap.dedent(
            """
            class InvoiceService:
                def create_invoice(self, account):
                    return account
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def _stable_evidence(ranked):
    """Return legacy ranking evidence that tracing must not alter."""
    return [
        (item.rel, item.score, item.reasons, item.term_hits, item.changed)
        for item in ranked
    ]


def test_score_tracing_is_opt_in_and_behavior_neutral(tmp_path):
    """Tracing must not change file order, scores, or legacy reason strings."""
    root = _repo(tmp_path)
    empty_registry = RankingStageRegistry(())

    plain = rank_files(
        root,
        "refresh session token",
        changed_boost=False,
        feedback_boost=False,
        stage_registry=empty_registry,
    )
    traced = rank_files(
        root,
        "refresh session token",
        changed_boost=False,
        feedback_boost=False,
        stage_registry=empty_registry,
        trace_scores=True,
    )

    assert _stable_evidence(plain) == _stable_evidence(traced)
    assert all(not item.score_trace for item in plain)
    assert all(item.score_trace for item in traced)
    for item in traced:
        assert item.score_trace[0].stage == "bm25"
        assert item.score_trace[0].before == 0.0
        assert math.isclose(item.score_trace[-1].after, item.score)
        assert math.isclose(
            sum(event.delta for event in item.score_trace),
            item.score,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )


def test_custom_reranker_is_traced_automatically(tmp_path):
    """Registry instrumentation should capture custom score/evidence mutations."""
    root = _repo(tmp_path)
    ranked = rank_files(
        root,
        "refresh session token",
        changed_boost=False,
        feedback_boost=False,
        stage_registry=RankingStageRegistry((_BoostStage(),)),
        trace_scores=True,
    )

    for item in ranked:
        event = item.score_trace[-1]
        assert event.stage == "test-boost"
        assert event.delta == 3.5
        assert event.evidence == ("custom:test-boost",)
        assert event.after == item.score


def test_registry_rejects_candidate_reordering_even_without_trace(tmp_path):
    """Extensions may mutate evidence/scores but not candidate membership/order."""
    root = _repo(tmp_path)
    with pytest.raises(ValueError, match="must not add, remove, or reorder"):
        rank_files(
            root,
            "refresh session token",
            changed_boost=False,
            feedback_boost=False,
            stage_registry=RankingStageRegistry((_ReorderStage(),)),
        )


def test_repository_service_explains_complete_score_trace(tmp_path):
    """Application service should return a machine-readable score breakdown."""
    root = _repo(tmp_path)
    report = RepositoryContextService(
        root,
        persist_index=False,
    ).explain_ranking(
        "refresh session token",
        max_files=2,
        changed_boost=False,
        feedback_boost=False,
        stage_registry=RankingStageRegistry(()),
    )

    assert report["query"] == "refresh session token"
    assert report["candidate_count"] == 2
    assert report["returned"] == 2
    first = report["results"][0]
    assert first["path"] == "auth.py"
    assert first["trace_complete"] is True
    assert first["trace"][0]["stage"] == "bm25"
    assert "file-priority" in first["stage_deltas"]
    assert math.isclose(
        sum(first["stage_deltas"].values()),
        first["final_score"],
        rel_tol=1e-12,
        abs_tol=1e-12,
    )


def test_ranking_explain_cli_supports_json_output(tmp_path, capsys):
    """CLI should expose the same structured explanation without host coupling."""
    root = _repo(tmp_path)

    result = ranking_explain_main(
        [
            str(root),
            "--query",
            "refresh session token",
            "--max-files",
            "1",
            "--json",
            "--no-changed-boost",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["returned"] == 1
    assert payload["results"][0]["trace_complete"] is True
    assert payload["results"][0]["trace"]


def test_mcp_explain_ranking_tool_returns_score_trace(tmp_path):
    """MCP clients should be able to inspect ranking decisions directly."""
    _repo(tmp_path)
    assert "explain_ranking" in {tool["name"] for tool in TOOLS}

    result = call_tool(
        tmp_path,
        "explain_ranking",
        {
            "query": "refresh session token",
            "max_files": 1,
            "changed_boost": False,
        },
    )

    payload = json.loads(result["content"][0]["text"])
    assert payload["returned"] == 1
    assert payload["results"][0]["trace_complete"] is True
    assert payload["results"][0]["trace"]

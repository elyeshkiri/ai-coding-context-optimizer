from acco.budget import plan_retrieval
from acco.pack import build_context_pack


def test_six_thousand_token_plan_preserves_v11_defaults():
    plan = plan_retrieval(
        max_tokens=6000,
        query_terms=4,
        changed_count=0,
        graph_hops=1,
        closure_items=20,
        context_lines=6,
    )
    assert plan.seed_limit == 6
    assert plan.graph_hops == 1
    assert plan.closure_items == 20
    assert plan.context_lines == 6


def test_small_budget_tightens_retrieval():
    plan = plan_retrieval(
        max_tokens=1500,
        query_terms=4,
        changed_count=0,
        graph_hops=2,
        closure_items=20,
        context_lines=6,
    )
    assert plan.seed_limit == 3
    assert plan.graph_hops == 1
    assert plan.closure_items == 8
    assert plan.context_lines == 4


def test_large_budget_widens_default_retrieval():
    plan = plan_retrieval(
        max_tokens=12000,
        query_terms=4,
        changed_count=0,
        graph_hops=1,
        closure_items=20,
        context_lines=6,
    )
    assert plan.seed_limit == 8
    assert plan.closure_items == 30
    assert plan.context_lines == 8


def test_large_diff_increases_seed_representation():
    plan = plan_retrieval(
        max_tokens=6000,
        query_terms=4,
        changed_count=11,
        graph_hops=1,
        closure_items=20,
        context_lines=6,
    )
    assert plan.seed_limit == 11


def test_context_pack_reports_effective_plan(tmp_path):
    (tmp_path / "service.py").write_text(
        "def refresh_session():\n    return True\n"
    )
    pack = build_context_pack(
        tmp_path,
        "refresh session",
        max_tokens=1200,
        changed_boost=False,
        persist_index=False,
    )
    assert pack.retrieval_plan["closure_items"] == 8
    assert pack.retrieval_plan["context_lines"] == 4


def test_adaptive_budget_can_be_disabled(tmp_path):
    (tmp_path / "service.py").write_text(
        "def refresh_session():\n    return True\n"
    )
    pack = build_context_pack(
        tmp_path,
        "refresh session",
        max_tokens=1200,
        changed_boost=False,
        persist_index=False,
        adaptive_budget=False,
    )
    assert pack.retrieval_plan == {
        "seed_limit": 6,
        "graph_hops": 1,
        "closure_items": 20,
        "context_lines": 6,
    }

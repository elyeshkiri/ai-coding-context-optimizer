"""Unit coverage for the individually-addressable ranking stages.

These stages were previously buried inside rank_files/_symbol_windows and
could only be exercised end-to-end through a full context pack. They are
pinned here directly so a change to one scoring rule fails a targeted test
rather than only shifting an aggregate benchmark number.
"""
from collections import Counter

from acco.pack import (
    _ACTION_TERMS,
    _apply_file_boosts,
    _bm25_score,
    _document_terms,
    _expand_query_terms,
    _FileRankingScope,
    _lexical_symbol_score,
    _rank_sort_key,
    _resolve_changed_files,
    _SymbolScope,
    RankedFile,
)
from acco.repo_index import build_index


def _scope(**overrides) -> _FileRankingScope:
    base = dict(
        index=None, q_terms=[], changed=set(), feedback={},
        remembered_files=set(), query_continues=False,
        authority_terms=set(), authority_pairs=set(),
        callable_file_counts=Counter(), query="",
    )
    base.update(overrides)
    return _FileRankingScope(**base)


class _FakeIndex:
    def __init__(self, records=None):
        self.records = records or {}


def test_bm25_reports_matched_term_count_and_zero_for_no_overlap():
    counts = Counter({"session": 3, "refresh": 1})
    doc_freq = Counter({"session": 1, "refresh": 1, "absent": 0})

    score, matched = _bm25_score(
        counts, ["session", "refresh"], doc_freq, length=4, avg_len=4.0, n_docs=10,
    )
    assert matched == 4
    assert score > 0

    score, matched = _bm25_score(
        counts, ["absent"], doc_freq, length=4, avg_len=4.0, n_docs=10,
    )
    assert (score, matched) == (0.0, 0)


def test_bm25_rewards_rarer_terms_more():
    counts = Counter({"rare": 1, "common": 1})
    doc_freq = Counter({"rare": 1, "common": 90})

    rare, _ = _bm25_score(counts, ["rare"], doc_freq, 2, 2.0, 100)
    common, _ = _bm25_score(counts, ["common"], doc_freq, 2, 2.0, 100)
    assert rare > common


def test_path_and_symbol_hits_are_recorded_as_reasons():
    scope = _scope(q_terms=["session"], index=_FakeIndex())
    reasons: list[str] = []

    score = _apply_file_boosts(scope, "src/session.py", "def session()", 0.0, reasons)

    assert "path:1" in reasons
    assert "symbols:1" in reasons
    assert score > 8.0


def test_low_value_directory_dampening_scales_with_score():
    """A test/doc file is dampened proportionally, not by a fixed amount."""
    scope = _scope(q_terms=[], index=_FakeIndex())

    big = _apply_file_boosts(scope, "tests/test_session.py", "", 100.0, [])
    small = _apply_file_boosts(scope, "tests/test_session.py", "", 10.0, [])

    assert big < 100.0 and small < 10.0
    # The penalty grows with the underlying score, which is the whole point
    # of dampening multiplicatively instead of subtracting a constant.
    assert (100.0 - big) > (10.0 - small)


def test_ordinary_source_file_is_not_dampened():
    scope = _scope(q_terms=[], index=_FakeIndex())

    source = _apply_file_boosts(scope, "src/acco/pack.py", "", 100.0, [])
    test_file = _apply_file_boosts(scope, "tests/test_pack.py", "", 100.0, [])

    assert source > 100.0
    assert test_file < source


def test_changed_and_working_set_boosts_are_additive_and_labelled():
    scope = _scope(
        q_terms=[], index=_FakeIndex(), changed={"a.py"},
        remembered_files={"a.py"}, query_continues=True,
    )
    reasons: list[str] = []
    boosted = _apply_file_boosts(scope, "a.py", "", 0.0, reasons)
    plain = _apply_file_boosts(_scope(index=_FakeIndex()), "a.py", "", 0.0, [])

    assert "changed" in reasons and "working-set" in reasons
    assert boosted - plain == 6.0, "changed (+4) and working-set (+2) are additive"


def test_feedback_boost_is_clamped_both_directions():
    reasons: list[str] = []
    positive = _apply_file_boosts(
        _scope(index=_FakeIndex(), feedback={"a.py": 99}), "a.py", "", 0.0, reasons,
    )
    negative = _apply_file_boosts(
        _scope(index=_FakeIndex(), feedback={"a.py": -99}), "a.py", "", 0.0, [],
    )
    assert positive - negative == 4.0  # +2.0 clamp minus -2.0 clamp
    assert any(reason.startswith("feedback:") for reason in reasons)


def test_rank_sort_key_orders_by_score_then_priority_then_path():
    def item(rel, score):
        return RankedFile(
            path=None, rel=rel, text="", outline="", score=score,
            reasons=[], term_hits=0, changed=False,
        )

    ordered = sorted(
        [item("b.py", 1.0), item("a.py", 5.0), item("c.py", 5.0)],
        key=_rank_sort_key,
    )
    assert [i.rel for i in ordered] == ["a.py", "c.py", "b.py"]


def test_document_terms_weighting_matches_index_formula():
    counts = _document_terms("", "alpha", "beta.py")
    assert counts["alpha"] == 2, "outline terms are deliberately counted twice"
    assert counts["beta"] == 3, "path terms carry a 3x weight"


def test_expand_query_terms_adds_correction_without_dropping_original(tmp_path):
    (tmp_path / "mod.py").write_text("def refresh_session():\n    return 1\n")
    index = build_index(tmp_path, persist=False)

    expanded = _expand_query_terms(index, "sesion")

    assert "sesion" in expanded, "the original term is never rewritten away"
    assert "session" in expanded, "a high-confidence correction is additive"


def test_expand_query_terms_leaves_unknown_words_alone(tmp_path):
    (tmp_path / "mod.py").write_text("def refresh_session():\n    return 1\n")
    index = build_index(tmp_path, persist=False)

    assert _expand_query_terms(index, "zqxjkv") == ["zqxjkv"]


def test_resolve_changed_files_honours_explicit_set_and_disable_flag(tmp_path):
    assert _resolve_changed_files(tmp_path, False, {"a.py"}) == set()
    assert _resolve_changed_files(tmp_path, True, {"a.py"}) == {"a.py"}


def test_lexical_symbol_score_prefers_identifier_over_body_matches():
    scope = _SymbolScope(
        rel="x.py", definitions=[], source_lines=[], container_names=set(),
        symbol_query_terms=set(), positive_query_terms=set(),
        negative_query_terms=set(), query_text="",
        identifier_terms_by_symbol={}, signature_terms_by_symbol={},
        leaf_terms_by_symbol={}, leaf_doc_freq=Counter(), fuzzy_query_terms={},
        term_weight={}, family_sizes=Counter(), family_term_freq={},
        family_body_shapes={}, explicit_member_hints=set(),
        array_preference=None, desired_parameter_count=None,
        declaration_preference=None,
    )
    identifier = _lexical_symbol_score(scope, {"session"}, set(), set())
    signature = _lexical_symbol_score(scope, set(), {"session"}, set())
    body = _lexical_symbol_score(scope, set(), set(), {"session"})

    assert identifier > signature > body


def test_action_verbs_score_lower_than_specific_identifiers():
    scope = _SymbolScope(
        rel="x.py", definitions=[], source_lines=[], container_names=set(),
        symbol_query_terms=set(), positive_query_terms=set(),
        negative_query_terms=set(), query_text="",
        identifier_terms_by_symbol={}, signature_terms_by_symbol={},
        leaf_terms_by_symbol={}, leaf_doc_freq=Counter(), fuzzy_query_terms={},
        term_weight={}, family_sizes=Counter(), family_term_freq={},
        family_body_shapes={}, explicit_member_hints=set(),
        array_preference=None, desired_parameter_count=None,
        declaration_preference=None,
    )
    action_only = _lexical_symbol_score(scope, {"build"}, set(), set())
    specific_only = _lexical_symbol_score(scope, {"session"}, set(), set())

    assert "build" in _ACTION_TERMS
    assert action_only < specific_only


def test_directory_terms_do_not_earn_path_credit():
    """A term shared by every file under a directory cannot tell them apart."""
    scope = _scope(q_terms=["pack"], index=_FakeIndex())

    in_directory: list[str] = []
    in_directory_score = _apply_file_boosts(
        scope, "src/packing/symbol_windows.py", "", 0.0, in_directory,
    )
    in_filename: list[str] = []
    in_filename_score = _apply_file_boosts(
        scope, "src/pack_cli.py", "", 0.0, in_filename,
    )

    assert not any(reason.startswith("path:") for reason in in_directory)
    assert "path:1" in in_filename
    assert in_filename_score > in_directory_score

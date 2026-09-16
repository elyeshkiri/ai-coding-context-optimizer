"""Token estimation."""

import pytest

from token_saver.estimate import (
    Counter,
    count_tokens_exact,
    estimate_tokens,
    format_tokens,
    ratio_for,
)


def test_empty():
    assert estimate_tokens("") == 0


def test_scales_with_length():
    assert estimate_tokens("x" * 4000, ".py") > estimate_tokens("x" * 400, ".py")


def test_json_counts_more_tokens_per_char_than_typescript():
    """Measured: JSON is punctuation-dense, TS has long identifiers."""
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".json") > estimate_tokens(blob, ".ts")


def test_code_is_denser_than_prose():
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".py") > estimate_tokens(blob, ".md")


def test_unknown_suffix_falls_back():
    assert estimate_tokens("x" * 1000, ".zzz") > 0
    assert ratio_for(".zzz") == ratio_for(".unknown")


def test_estimates_are_conservative_versus_chars_over_4():
    """Ratios bias high on code: a tight budget is cheaper to find than a blown one."""
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".py") > len(blob) // 4


def test_counter_label():
    assert Counter().label == "≈est"
    assert Counter(exact=True).label == "exact"


def test_counter_estimates_without_network():
    assert Counter().count("hello world", ".py") > 0


def test_exact_mode_reports_a_usable_error_without_the_sdk(monkeypatch):
    """Without the SDK installed the failure must name the fix, not traceback."""
    import builtins

    real_import = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeError, match="token-saver\\[exact\\]"):
        count_tokens_exact("hi")


def test_format_tokens():
    assert format_tokens(999) == "999"
    assert format_tokens(1500) == "1.5k"
    assert format_tokens(2_500_000) == "2.5M"

"""Token estimation and provider-aware exact counting."""

import sys
from types import SimpleNamespace

import pytest

from token_saver.estimate import (
    Counter,
    count_tokens_exact,
    estimate_tokens,
    format_tokens,
    provider_for_model,
    ratio_for,
)


def test_empty():
    assert estimate_tokens("") == 0


def test_scales_with_length():
    assert estimate_tokens("x" * 4000, ".py") > estimate_tokens("x" * 400, ".py")


def test_json_counts_more_tokens_per_char_than_typescript():
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".json") > estimate_tokens(blob, ".ts")


def test_code_is_denser_than_prose():
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".py") > estimate_tokens(blob, ".md")


def test_unknown_suffix_falls_back():
    assert estimate_tokens("x" * 1000, ".zzz") > 0
    assert ratio_for(".zzz") == ratio_for(".unknown")


def test_estimates_are_conservative_versus_chars_over_4():
    blob = "x" * 10_000
    assert estimate_tokens(blob, ".py") > len(blob) // 4


def test_counter_label():
    assert Counter().label == "≈est"
    assert Counter(exact=True).label == "exact"
    assert Counter(exact=True).provider_label == "anthropic"


def test_counter_estimates_without_network():
    assert Counter().count("hello world", ".py") > 0


def test_provider_is_inferred_from_model_family():
    assert provider_for_model("claude-sonnet-4-5") == "anthropic"
    assert provider_for_model("gpt-4o") == "openai"
    assert provider_for_model("o3-mini") == "openai"
    assert provider_for_model("custom-model") is None


def test_exact_mode_reports_a_usable_error_without_the_sdk(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeError, match="token-saver\\[exact\\]"):
        count_tokens_exact("hi")


def test_openai_exact_mode_uses_model_tokenizer(monkeypatch):
    class Encoding:
        def encode(self, text):
            return text.split()

    fake = SimpleNamespace(encoding_for_model=lambda model: Encoding())
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    assert count_tokens_exact(
        "one two three", model="gpt-4o", provider="openai"
    ) == 3


def test_openai_unknown_tokenizer_is_not_silently_approximated(monkeypatch):
    def missing(_model):
        raise KeyError("unknown")

    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(encoding_for_model=missing))
    with pytest.raises(RuntimeError, match="does not have an exact tokenizer mapping"):
        count_tokens_exact("hi", model="gpt-future-unknown", provider="openai")


def test_unknown_provider_requires_explicit_choice():
    with pytest.raises(RuntimeError, match="unsupported token-counting provider"):
        count_tokens_exact("hi", model="local-model")


def test_format_tokens():
    assert format_tokens(999) == "999"
    assert format_tokens(1500) == "1.5k"
    assert format_tokens(2_500_000) == "2.5M"

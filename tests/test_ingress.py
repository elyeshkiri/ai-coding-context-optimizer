"""Tests for lossless oversized-prompt ingress staging."""

from __future__ import annotations

import pytest

from token_saver.ingress import (
    _paths,
    load_stage,
    maybe_stage_prompt,
    read_stage,
    stage_prompt,
)


def _large_prompt() -> str:
    """Return a deterministic multi-line prompt with important tail instructions."""
    lines = [f"evidence line {index}: " + ("detail " * 10) for index in range(1, 181)]
    lines.extend(
        [
            "FINAL REQUIREMENT: preserve database compatibility.",
            "FINAL REQUIREMENT: run the regression suite.",
        ]
    )
    return "\n".join(lines)


def test_stage_prompt_is_lossless_recoverable_and_bounded(tmp_path, monkeypatch):
    """Staging should preserve the exact original while emitting a small packet."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    prompt = _large_prompt()

    stage = stage_prompt(root, prompt, packet_tokens=500)

    assert stage.original_tokens > stage.packet_tokens
    assert stage.packet_tokens <= 500
    assert "was NOT sent to the model" in stage.packet
    assert "lines " in stage.packet and "omitted" in stage.packet
    assert "FINAL REQUIREMENT: run the regression suite." in stage.packet
    assert stage.omitted_start_line is not None
    assert stage.omitted_end_line is not None

    loaded = load_stage(root, stage.id)
    assert loaded == stage

    start = stage.omitted_start_line
    end = min(start + 2, stage.omitted_end_line)
    expected = "\n".join(prompt.splitlines()[start - 1:end]) + "\n"
    assert read_stage(root, stage.id, start_line=start, end_line=end) == expected


def test_stage_integrity_failure_is_explicit(tmp_path, monkeypatch):
    """Tampering with the exact stored original must fail instead of degrading."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    stage = stage_prompt(root, _large_prompt(), packet_tokens=500)
    _meta, original = _paths(root, stage.id)
    original.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="integrity check failed"):
        load_stage(root, stage.id)


def test_ingress_is_opt_in_and_threshold_gated(tmp_path, monkeypatch):
    """Ordinary prompts and disabled ingress must remain untouched."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    prompt = _large_prompt()

    assert maybe_stage_prompt(
        root,
        prompt,
        enabled=False,
        threshold_tokens=100,
        packet_tokens=400,
    ) is None
    assert maybe_stage_prompt(
        root,
        "small prompt",
        enabled=True,
        threshold_tokens=100,
        packet_tokens=400,
    ) is None
    assert maybe_stage_prompt(
        root,
        prompt,
        enabled=True,
        threshold_tokens=100,
        packet_tokens=400,
    ) is not None


def test_ingress_read_rejects_invalid_ranges(tmp_path, monkeypatch):
    """Recovery should require explicit valid bounded line ranges."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    stage = stage_prompt(root, _large_prompt(), packet_tokens=500)

    with pytest.raises(ValueError, match="1 <= start <= end"):
        read_stage(root, stage.id, start_line=0, end_line=2)
    with pytest.raises(ValueError, match="exceeds"):
        read_stage(
            root,
            stage.id,
            start_line=1,
            end_line=stage.original_lines + 1,
        )

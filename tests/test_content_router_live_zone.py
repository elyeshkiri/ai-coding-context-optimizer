"""Regression tests for generic payload routing and cache-preserving live zones."""

from __future__ import annotations

import json

from acco.output import OutputPipeline
from acco.prefix_cache import observe_prefix
from acco.provider_transform import transform_provider_request


def test_json_payload_preserves_anomaly_outside_edges():
    """Large JSON arrays retain diagnostic records even when they are deep inside."""
    rows = [{"id": index, "status": "ok", "value": "x" * 40} for index in range(80)]
    rows[41] = {"id": 41, "status": "error", "error": "rare failure marker"}
    raw = json.dumps(rows, indent=2)

    result = OutputPipeline().process(raw, "unknown-tool")

    assert result.compressed is True
    assert result.processor == "payload-json"
    assert "rare failure marker" in result.text
    assert "_acco_omitted_items" in result.text


def test_delimited_payload_routes_without_command_specific_knowledge():
    """Unknown CSV-like tool output gets bounded by payload shape."""
    lines = ["id,status,value"]
    lines.extend(f"{i},ok,{'x' * 40}" for i in range(100))
    lines[55] = "54,error,rare failure marker"
    raw = "\n".join(lines) + "\n"

    result = OutputPipeline().process(raw, "custom-agent-tool")

    assert result.compressed is True
    assert result.processor == "payload-delimited"
    assert "rare failure marker" in result.text
    assert "row(s) omitted" in result.text


def test_live_zone_leaves_cache_hot_openai_history_byte_identical(tmp_path, monkeypatch):
    """Previously observed OpenAI input history must not be rewritten on the next turn."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    old_output = "\n".join(f"old {i} {'x' * 80}" for i in range(180))
    first = {
        "model": "gpt-test",
        "input": [
            {"type": "function_call_output", "call_id": "old", "output": old_output},
            {"role": "user", "content": "first task"},
        ],
    }
    observe_prefix(root, "openai", first)

    new_output = "\n".join(f"new {i} {'y' * 80}" for i in range(180))
    second = {
        "model": "gpt-test",
        "input": [
            {"type": "function_call_output", "call_id": "old", "output": old_output},
            {"role": "user", "content": "first task"},
            {"type": "function_call_output", "call_id": "new", "output": new_output},
            {"role": "user", "content": "second task"},
        ],
    }

    result = transform_provider_request(
        root,
        "openai",
        second,
        request_path="/v1/responses",
        compress_schemas=False,
        deduplicate_history=False,
        tool_result_min_tokens=100,
        prefix_tracking=True,
        live_zone=True,
    )

    assert result.body["input"][0]["output"] == old_output
    assert result.body["input"][2]["output"] != new_output
    assert result.transformed_segments == 1

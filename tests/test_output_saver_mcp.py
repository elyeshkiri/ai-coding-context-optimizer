import json

from token_saver.serve import call_tool


def _payload(result):
    return json.loads(result["content"][0]["text"])


def test_mcp_output_policy_exposes_generation_budget(tmp_path):
    result = call_tool(tmp_path, "output_policy", {"mode": "terse", "max_tokens": 220})
    payload = _payload(result)

    assert payload["mode"] == "terse"
    assert payload["max_tokens"] == 220
    assert "target <= 220 tokens" in payload["instructions"]


def test_mcp_compact_output_reports_savings(tmp_path):
    result = call_tool(
        tmp_path,
        "compact_output",
        {
            "text": "Sure!\n\nDone.\n\nDone.\n",
            "mode": "terse",
        },
    )
    payload = _payload(result)

    assert payload["text"] == "Done."
    assert payload["output_tokens"] < payload["original_tokens"]
    assert payload["code_preserved"] is True

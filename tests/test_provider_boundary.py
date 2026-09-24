"""Tests for broader provider-boundary interception and usage evidence."""

from __future__ import annotations

import json

from acco.efficiency.store import load_events
from acco.provider_boundary import detect_provider_request
from acco.provider_proxy import ProviderProxyConfig, transform_request_bytes
from acco.provider_transform import transform_provider_request
from acco.provider_usage import ProviderUsageObserver, normalize_provider_usage
from acco.recovery import RecoveryStore
from acco.tool_schema import compress_tool_catalog


def _noise(prefix: str, rows: int = 180) -> str:
    """Return a large deterministic tool payload."""
    return "\n".join(
        f"{prefix} {index} " + "x" * 80 for index in range(rows)
    )


def test_provider_auto_detection_distinguishes_common_api_shapes():
    """Auto mode should recognize Anthropic, OpenAI, and Gemini boundaries."""
    assert detect_provider_request(
        "auto",
        {"messages": []},
        path="/v1/chat/completions",
    ).shape == "openai-chat"
    assert detect_provider_request(
        "auto",
        {"input": "hello"},
        path="/v1/responses",
    ).shape == "openai-responses"
    assert detect_provider_request(
        "auto",
        {"messages": [], "max_tokens": 100, "system": "x"},
        path="/v1/messages",
    ).provider == "anthropic"
    assert detect_provider_request(
        "auto",
        {"contents": []},
        path="/v1beta/models/gemini:streamGenerateContent",
    ).streaming is True


def test_openai_responses_compresses_only_historical_function_output(
    tmp_path, monkeypatch
):
    """OpenAI Responses current user input must remain byte-for-byte unchanged."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    current = "Please debug the authentication failure without changing scope."
    historical = _noise("pytest")
    body = {
        "model": "gpt-test",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": historical,
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": current}],
            },
        ],
    }

    result = transform_provider_request(
        root,
        "auto",
        body,
        request_path="/v1/responses",
        tool_result_min_tokens=100,
        compress_schemas=False,
        prefix_tracking=False,
    )

    assert result.profile.provider == "openai"
    assert result.profile.shape == "openai-responses"
    assert result.changed is True
    assert result.transformed_segments == 1
    assert result.body["input"][1] == body["input"][1]
    handle = result.recovery_handles[0]
    assert RecoveryStore(root).get(handle).payload.decode() == historical
    assert result.metadata()["policy"] == "retrieval-first-historical-only"


def test_gemini_function_response_preserves_structure_and_user_prompt(
    tmp_path, monkeypatch
):
    """Gemini nested functionResponse strings may shrink without rewriting structure."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    current = "Find the exact failing handler."
    historical = _noise("browser")
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "browser_snapshot",
                            "response": {
                                "status": "ok",
                                "output": historical,
                            },
                        }
                    }
                ],
            },
            {
                "role": "user",
                "parts": [{"text": current}],
            },
        ]
    }

    result = transform_provider_request(
        root,
        "auto",
        body,
        request_path="/v1beta/models/gemini-2:generateContent",
        tool_result_min_tokens=100,
        compress_schemas=False,
        prefix_tracking=False,
    )

    response = result.body["contents"][0]["parts"][0]["functionResponse"]["response"]
    assert result.profile.provider == "gemini"
    assert result.changed is True
    assert isinstance(response, dict)
    assert response["status"] == "ok"
    assert response["output"] != historical
    assert result.body["contents"][1]["parts"][0]["text"] == current
    assert RecoveryStore(root).get(result.recovery_handles[0]).payload.decode() == historical


def test_nested_openai_and_gemini_tool_schemas_compress_with_exact_recovery(
    tmp_path, monkeypatch
):
    """Provider wrapper shapes should reuse the same conservative schema compressor."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    store = RecoveryStore(root)
    verbose = (
        "Search repository evidence for the requested symbol. " * 18
        + "The path must be absolute. Exactly one query is required."
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_repo",
                "description": verbose,
                "parameters": {
                    "type": "object",
                    "title": "drop",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": verbose,
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "functionDeclarations": [
                {
                    "name": "read_repo",
                    "description": verbose,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": verbose}
                        },
                        "required": ["path"],
                    },
                }
            ]
        },
    ]

    result = compress_tool_catalog(tools, recovery=store, min_reduction=0.0)

    assert result.changed is True
    assert result.recovery_handle
    openai = result.value[0]["function"]
    gemini = result.value[1]["functionDeclarations"][0]
    assert len(openai["description"]) < len(verbose)
    assert "title" not in openai["parameters"]
    assert len(gemini["description"]) < len(verbose)
    assert json.loads(store.get(result.recovery_handle).payload) == tools


def test_proxy_transform_auto_detects_provider_from_request_path(
    tmp_path, monkeypatch
):
    """Transparent proxy mode should not require duplicating provider config."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    config = ProviderProxyConfig(
        root=root,
        upstream="https://api.openai.example",
        provider="auto",
        prefix_tracking=False,
    )
    raw = json.dumps(
        {
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": _noise("tool"),
                }
            ]
        }
    ).encode()

    result = transform_request_bytes(
        config,
        raw,
        content_type="application/json",
        request_path="/v1/responses",
    )

    assert result.metadata["request"]["provider"] == "openai"
    assert result.metadata["request"]["shape"] == "openai-responses"


def test_provider_usage_normalization_covers_all_three_providers():
    """Provider-specific counters should map into one content-free schema."""
    assert normalize_provider_usage(
        "anthropic",
        {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 40,
            }
        },
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 40,
    }
    assert normalize_provider_usage(
        "openai",
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 40},
            }
        },
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cache_read_input_tokens": 40,
    }
    assert normalize_provider_usage(
        "gemini",
        {
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 20,
                "cachedContentTokenCount": 40,
                "totalTokenCount": 120,
            }
        },
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 40,
        "total_tokens": 120,
    }


def test_streaming_usage_observer_forwards_no_content_into_event_store(
    tmp_path, monkeypatch
):
    """SSE observation should persist counters/model only, never response text."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    observer = ProviderUsageObserver(
        root,
        provider="openai",
        request_shape="openai-responses",
        streaming=True,
        content_type="text/event-stream",
    )
    observer.feed(
        b'data: {"type":"response.output_text.delta","delta":"SECRET RESPONSE"}\n'
    )
    observer.feed(
        b'data: {"model":"gpt-test","usage":{"input_tokens":120,'
        b'"output_tokens":30,"total_tokens":150}}\n\n'
    )
    event = observer.finish()

    assert event["input_tokens"] == 120
    assert event["output_tokens"] == 30
    assert event["model"] == "gpt-test"
    stored = load_events(root)[-1]
    assert stored["kind"] == "provider_usage"
    assert "SECRET RESPONSE" not in json.dumps(stored)


def test_json_usage_observer_handles_gemini_array_response(tmp_path, monkeypatch):
    """Gemini streamed JSON arrays should yield the largest cumulative usage."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    observer = ProviderUsageObserver(
        root,
        provider="gemini",
        request_shape="gemini-generate-content",
        streaming=False,
        content_type="application/json",
    )
    observer.feed(
        json.dumps(
            [
                {"usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 5}},
                {
                    "modelVersion": "gemini-test",
                    "usageMetadata": {
                        "promptTokenCount": 90,
                        "candidatesTokenCount": 12,
                        "totalTokenCount": 102,
                    },
                },
            ]
        ).encode()
    )

    event = observer.finish()

    assert event["input_tokens"] == 90
    assert event["output_tokens"] == 12
    assert event["total_tokens"] == 102
    assert event["model"] == "gemini-test"

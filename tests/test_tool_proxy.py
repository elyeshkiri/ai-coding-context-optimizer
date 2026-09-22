"""Tests for free/local-model guided Read result proxying."""

from __future__ import annotations

import json
from pathlib import Path

from acco.guard import decide_read
from acco.runtime_config import settings_for
from acco.tool_proxy import latest_user_task, proxy_read


def _large_source(path: Path, *, lines: int = 260) -> str:
    """Write a large source fixture with one task-relevant implementation."""
    body = [f"value_{index} = {index}" for index in range(lines)]
    body[140:145] = [
        "def refresh_session(token):",
        "    if token.expired:",
        "        raise ValueError('expired')",
        "    return rotate_token(token)",
        "",
    ]
    text = "\n".join(body) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def test_latest_user_task_reads_only_latest_user_message(tmp_path):
    """Transcript context should orient selection without persisting conversation text."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [{"type": "text", "text": "old task"}]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "assistant text"}]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "fix refresh_session token expiry",
                                }
                            ]
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert latest_user_task(transcript) == "fix refresh_session token expiry"


def test_proxy_is_opt_in(tmp_path):
    """Disabled proxying must preserve the historical hook behavior."""
    source = tmp_path / "service.py"
    content = _large_source(source)

    assert proxy_read(tmp_path, source, content, enabled=False, min_tokens=1) is None


def test_deterministic_fallback_returns_exact_task_relevant_source(tmp_path):
    """A missing free model should still return bounded exact source evidence."""
    source = tmp_path / "service.py"
    content = _large_source(source)
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "fix refresh_session token expiry",
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = proxy_read(
        tmp_path,
        source,
        content,
        transcript_path=transcript,
        enabled=True,
        provider="deterministic",
        min_tokens=1,
        target_tokens=700,
        model_input_tokens=1200,
        max_ranges=2,
        max_range_lines=40,
    )

    assert result is not None
    assert "TOKEN SAVER SMART READ" in result
    assert "selector: deterministic-fallback" in result
    assert "def refresh_session(token):" in result
    assert "raise ValueError('expired')" in result
    assert "RECOVERY:" in result
    assert len(result) < len(content)


def test_ollama_range_selection_is_rehydrated_from_exact_source(tmp_path, monkeypatch):
    """Model-provided ranges may select evidence but cannot invent delivered code."""
    source = tmp_path / "service.py"
    content = _large_source(source)

    class _Response:
        """Minimal context-manager response used to fake Ollama."""

        def __enter__(self):
            """Return this fake response."""
            return self

        def __exit__(self, exc_type, exc, tb):
            """Close the fake response without suppressing exceptions."""
            return False

        def read(self):
            """Return one valid Ollama response envelope."""
            selected = {
                "ranges": [{"start": 141, "end": 144}],
            }
            return json.dumps({"response": json.dumps(selected)}).encode()

    monkeypatch.setattr(
        "acco.tool_proxy.request.urlopen",
        lambda *args, **kwargs: _Response(),
    )

    result = proxy_read(
        tmp_path,
        source,
        content,
        enabled=True,
        provider="ollama",
        model="free-coder",
        min_tokens=1,
        target_tokens=800,
        max_ranges=2,
        max_range_lines=20,
    )

    assert result is not None
    assert "selector: ollama:free-coder" in result
    assert "No selector-generated prose is forwarded" in result
    assert "def refresh_session(token):" in result
    assert "return rotate_token(token)" in result


def test_guard_delegates_eligible_large_read_to_posttool_proxy(tmp_path, monkeypatch):
    """Enabled proxying should let eligible full Reads reach PostToolUse."""
    source = tmp_path / "service.py"
    _large_source(source)
    monkeypatch.setenv("ACCO_TOOL_PROXY", "1")
    monkeypatch.setenv("ACCO_TOOL_PROXY_MIN_TOKENS", "1")

    assert decide_read({"file_path": str(source)}, cwd=tmp_path) is None


def test_tool_proxy_config_resolves_toml_and_environment(tmp_path, monkeypatch):
    """Project policy should be explicit and environment overrides should win."""
    (tmp_path / ".acco.toml").write_text(
        """[tool_proxy]
enabled = true
provider = "deterministic"
model = "tiny-coder"
endpoint = "http://127.0.0.1:9999"
min_tokens = 3000
target_tokens = 1200
model_input_tokens = 9000
timeout_seconds = 4.5
max_ranges = 3
max_range_lines = 60
""",
        encoding="utf-8",
    )

    configured = settings_for(tmp_path)
    assert configured.tool_proxy_enabled is True
    assert configured.tool_proxy_provider == "deterministic"
    assert configured.tool_proxy_model == "tiny-coder"
    assert configured.tool_proxy_min_tokens == 3000
    assert configured.tool_proxy_timeout_seconds == 4.5

    monkeypatch.setenv("ACCO_TOOL_PROXY", "0")
    monkeypatch.setenv("ACCO_TOOL_PROXY_PROVIDER", "ollama")
    monkeypatch.setenv("ACCO_TOOL_PROXY_MODEL", "local-model")
    monkeypatch.setenv("ACCO_TOOL_PROXY_MIN_TOKENS", "4200")
    monkeypatch.setenv("ACCO_TOOL_PROXY_MAX_RANGE_LINES", "44")
    overridden = settings_for(tmp_path)

    assert overridden.tool_proxy_enabled is False
    assert overridden.tool_proxy_provider == "ollama"
    assert overridden.tool_proxy_model == "local-model"
    assert overridden.tool_proxy_min_tokens == 4200
    assert overridden.tool_proxy_max_range_lines == 44

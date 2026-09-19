"""Tests for the host-neutral hook runtime boundary."""

from pathlib import Path

from token_saver.hook_runtime import HookConfig, HookRuntime, HookServices
from token_saver.output import OutputResult


class _PassthroughPipeline:
    """Minimal output pipeline used by runtime unit tests."""

    def process(self, text, command="", *, exit_code=None, policy=None):
        """Return the original text as an uncompressed output result."""

        return OutputResult(text, "test", False, bool(exit_code))


def _services(**overrides):
    """Return inert hook services with explicit overrides for one test."""

    defaults = {
        "guard": lambda payload: (0, None),
        "output_pipeline": _PassthroughPipeline(),
        "apply_delta": (
            lambda root, command, original, fallback, **kwargs: (fallback, {})
        ),
        "store_output": lambda response: "stored",
        "user_nudge": lambda root, prompt: None,
        "reset_session": lambda root, **kwargs: None,
        "record_read": lambda root, path, digest, **kwargs: None,
        "digest": lambda text: "digest",
        "estimate_tokens": lambda text: len(text),
    }
    defaults.update(overrides)
    return HookServices(**defaults)


def _bash_payload(stdout: str) -> dict:
    """Build a normalized Claude-style Bash post-tool payload."""

    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "cwd": ".",
        "tool_input": {"command": "custom build"},
        "tool_response": {
            "stdout": stdout,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
            "exit_code": 0,
        },
    }


def test_runtime_routes_pretool_events_to_injected_guard():
    """Pre-tool routing should depend on the guard contract, not a concrete module."""

    seen = []

    def guard(payload):
        """Capture the normalized payload passed to the injected guard."""

        seen.append(payload)
        return 0, {"guarded": True}

    runtime = HookRuntime(_services(guard=guard))
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "large.py"},
    }

    assert runtime.run(payload) == (0, {"guarded": True})
    assert seen == [payload]


def test_runtime_uses_injected_output_pipeline_and_store():
    """Post-tool output should flow through injected optimization and persistence."""

    filtered = []
    stored = []

    class CompactPipeline:
        """Pipeline test double that returns a deterministic compact candidate."""

        def process(self, text, command="", *, exit_code=None, policy=None):
            """Capture pipeline inputs and return a compact result."""

            filtered.append(
                (
                    text,
                    {
                        "command": command,
                        "exit_code": exit_code,
                        "policy": policy,
                    },
                )
            )
            return OutputResult("summary\n", "custom", True, bool(exit_code))

    def store_output(response):
        """Capture the original response before returning its recovery identifier."""

        stored.append(response)
        return "abc123"

    original = "\n".join(f"long build output {i:03d} " + "x" * 60 for i in range(80))
    runtime = HookRuntime(
        _services(output_pipeline=CompactPipeline(), store_output=store_output),
        HookConfig(min_lines=1, min_net_tokens=0, max_lines=10),
    )

    code, response = runtime.run(_bash_payload(original))

    assert code == 0
    assert response is not None
    updated = response["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    assert updated.startswith("summary\n")
    assert "abc123" in updated
    assert filtered[0][1]["policy"].max_lines == 10
    assert stored and stored[0]["stdout"] == original


def test_runtime_injects_session_and_prompt_services(tmp_path):
    """Session reset and prompt nudges should be supplied by application services."""

    reset_calls = []
    prompt_calls = []

    def reset_session(root, **kwargs):
        """Capture session reset calls."""

        reset_calls.append((root, kwargs))

    def user_nudge(root, prompt):
        """Capture prompt calls and return a deterministic nudge."""

        prompt_calls.append((root, prompt))
        return "use bounded context"

    runtime = HookRuntime(
        _services(reset_session=reset_session, user_nudge=user_nudge)
    )
    assert runtime.run(
        {
            "hook_event_name": "SessionStart",
            "cwd": str(tmp_path),
            "source": "resume",
            "session_id": "session",
        }
    ) == (0, None)
    assert reset_calls == [
        (
            Path(tmp_path),
            {"reads": False, "reminder": True, "session_id": "session"},
        )
    ]

    code, response = runtime.run(
        {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(tmp_path),
            "prompt": "fix the bug",
        }
    )
    assert code == 0
    assert response == {"systemMessage": "use bounded context"}
    assert prompt_calls == [(Path(tmp_path), "fix the bug")]


def test_runtime_records_verified_full_read_with_injected_state_services(tmp_path):
    """Full-read tracking should depend only on digest and record-read contracts."""

    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    recorded = []

    def record_read(root, path, digest, **kwargs):
        """Capture read-state writes."""

        recorded.append((root, path, digest, kwargs))

    runtime = HookRuntime(
        _services(
            digest=lambda text: f"digest:{len(text)}",
            record_read=record_read,
        )
    )
    runtime.run(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "cwd": str(tmp_path),
            "session_id": "s1",
            "tool_input": {"file_path": str(source)},
            "tool_response": {"file": {"content": "value = 1\n"}},
        }
    )

    assert recorded == [
        (
            Path(tmp_path),
            source,
            "digest:10",
            {"session_id": "s1"},
        )
    ]


def test_runtime_disabled_short_circuits_all_services():
    """The kill switch should stop routing before any injected service is called."""

    called = []

    def guard(payload):
        """Fail the test if a disabled runtime still reaches the guard."""

        called.append(payload)
        return 0, {"unexpected": True}

    runtime = HookRuntime(_services(guard=guard), HookConfig(disabled=True))
    assert runtime.run({"hook_event_name": "PreToolUse", "tool_name": "Read"}) == (
        0,
        None,
    )
    assert called == []

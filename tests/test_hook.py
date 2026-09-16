"""The PostToolUse hook that makes `filter` fire without being remembered."""

import io
import json

import pytest

from token_saver.hook import cap_for, main, run


def _payload(response, tool="Bash", command="npm test"):
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {"command": command},
        "tool_response": ({"stdout": response, "stderr": "", "interrupted": False, "isImage": False}
                          if isinstance(response, str) else response),
    }


def _updated(payload):
    code, response = run(payload)
    assert code == 0
    return response["hookSpecificOutput"]["updatedToolOutput"]["stdout"] if response else None


def test_large_bash_output_is_filtered():
    noisy = "\n".join(f"line {i}" for i in range(500))
    out = _updated(_payload(noisy))
    assert out is not None
    assert len(out.splitlines()) < 120
    assert "token-saver: filtered" in out


def test_session_start_resume_does_not_treat_matcher_as_clear(tmp_path):
    from token_saver.state import record_read, load as load_state

    p = tmp_path / "a.py"
    p.write_text("x = 1\n")
    record_read(tmp_path, p, "deadbeef")
    code, response = run({
        "hook_event_name": "SessionStart",
        "cwd": str(tmp_path),
        "source": "resume",
        "matcher": "startup|resume|clear",
    })
    assert code == 0
    assert response is None
    assert load_state(tmp_path).get("reads")


def test_session_start_without_transcripts_is_silent(tmp_path):
    code, response = run({"hook_event_name": "SessionStart", "cwd": str(tmp_path)})
    assert code == 0
    assert response is None


def test_small_output_is_left_alone():
    """Rewriting a short result risks losing detail for no gain."""
    assert _updated(_payload("\n".join(f"line {i}" for i in range(30)))) is None


def test_non_bash_tools_are_never_rewritten():
    """Outlining a Read would break Edit, which matches on exact file content."""
    body = "\n".join(f"line {i}" for i in range(500))
    assert _updated(_payload(body, tool="Read")) is None
    assert _updated(_payload(body, tool="Edit")) is None
    assert _updated(_payload(body, tool="Grep")) is None
    assert _updated(_payload(body, tool="WebFetch")) is None
    assert _updated(_payload(body, tool="mcp__github__search")) is None


def test_output_is_never_replaced_with_something_larger():
    noisy = "\n".join("error!" for _ in range(200))
    out = _updated(_payload(noisy))
    if out is not None:
        assert len(out) < len(noisy) + 200


def test_empty_response_is_ignored():
    assert _updated(_payload("")) is None
    assert _updated(_payload("   \n  ")) is None


def test_missing_fields_do_not_crash():
    assert run({}) == (0, None)
    assert run({"tool_name": "Bash"}) == (0, None)


def _log(n, width=90):
    """n lines of realistic width — real build output is not `line 7`."""
    return "\n".join(f"{i:04d} {'compiling module ' + str(i):<{width}}" for i in range(n))


def test_short_output_is_left_alone():
    """Median real Bash output is 8 lines. It must never be touched."""
    assert _updated(_payload(_log(8))) is None
    assert _updated(_payload(_log(39))) is None


def test_default_floor_filters_moderate_output():
    """The old 120-line floor fired on 2.8% of real calls. 40 is the point."""
    out = _updated(_payload(_log(60)))
    assert out is not None
    assert len(out.splitlines()) < 60


def test_cap_scales_with_input():
    """A huge log keeps more lines than a merely large one."""
    assert cap_for(50) < cap_for(500) < cap_for(5000)
    big = _updated(_payload(_log(1500)))
    assert big is not None
    # the 90-line cap for huge logs, plus banners/errors/tail markers
    assert 60 < len(big.splitlines()) < 160


def test_marginal_saving_is_refused(monkeypatch):
    """The note costs ~30 tokens. Filtering must not be a net loss."""
    monkeypatch.setenv("TOKEN_SAVER_MIN_LINES", "10")
    monkeypatch.setenv("TOKEN_SAVER_MAX_LINES", "8")
    tiny = "\n".join(f"{i}" for i in range(12))
    assert _updated(_payload(tiny)) is None, "saved less than the note it adds"


def test_thresholds_are_configurable(monkeypatch):
    """Env overrides still win over the defaults."""
    body = _log(60)
    monkeypatch.setenv("TOKEN_SAVER_MIN_LINES", "500")
    assert _updated(_payload(body)) is None, "floor raised above the input"

    monkeypatch.setenv("TOKEN_SAVER_MIN_LINES", "10")
    monkeypatch.setenv("TOKEN_SAVER_MAX_LINES", "8")
    out = _updated(_payload(body))
    assert out is not None
    assert len(out.splitlines()) < len(body.splitlines())


def test_main_passes_through_invalid_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    assert main() == 0
    assert capsys.readouterr().out == "", "no output means Claude keeps the original"


def test_main_emits_valid_json_for_a_big_payload(monkeypatch, capsys):
    noisy = "\n".join(f"line {i}" for i in range(500))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(noisy))))
    assert main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "updatedToolOutput" in parsed["hookSpecificOutput"]


def test_a_hook_crash_never_breaks_the_tool_call(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload("x\n" * 500))))
    monkeypatch.setattr("token_saver.hook.filter_command_output",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("bad", ["[]", '"a string"', "null"])
def test_non_object_payloads_pass_through(monkeypatch, capsys, bad):
    monkeypatch.setattr("sys.stdin", io.StringIO(bad))
    assert main() == 0
    assert capsys.readouterr().out == ""

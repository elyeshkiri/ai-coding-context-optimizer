"""Transcript analysis — measuring where tokens actually went."""

import json

import pytest

from acco.sessions import (
    OUTLINE_SUFFIXES,
    REPRIME_MIN_TOKENS,
    analyze,
    project_slug,
    transcript_paths,
)


def _assistant(tool_id, name, usage=None):
    return {
        "type": "assistant",
        "message": {
            "usage": usage or {},
            "content": [{"type": "tool_use", "id": tool_id, "name": name}],
        },
    }


def _result(tool_id, payload):
    return {
        "type": "user",
        "message": {"content": [{"tool_use_id": tool_id, "type": "tool_result"}]},
        "toolUseResult": payload,
    }


def _write(tmp_path, records, name="s.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def test_usage_is_summed_across_turns(tmp_path):
    usage = {
        "input_tokens": 10,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 900,
        "output_tokens": 5,
    }
    path = _write(tmp_path, [_assistant("t1", "Bash", usage), _assistant("t2", "Bash", usage)])
    report = analyze([path])
    assert report.usage["cache_read_input_tokens"] == 1800
    assert report.fresh_input == 220
    assert report.cache_hit_rate == pytest.approx(1800 / 2020)


def test_tool_results_are_attributed_to_the_right_tool(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Bash"),
            _result("t1", {"stdout": "x" * 400}),
            _assistant("t2", "Read"),
            _result("t2", {"file": {"filePath": "/a/b.py", "content": "y" * 4000}}),
        ],
    )
    report = analyze([path])
    names = {name: tokens for name, tokens, _ in report.by_tool()}
    assert set(names) == {"Bash", "Read"}
    assert names["Read"] > names["Bash"]


def test_image_results_are_separated_from_text(tmp_path):
    """Regression: base64 screenshots were counted as outlinable file reads."""
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Read"),
            _result("t1", {"type": "image", "file": {"base64": "iVBOR" * 5000}}),
        ],
    )
    report = analyze([path])
    tokens, count = report.image_cost()
    assert count == 1 and tokens == 0
    assert report.calls[0].unknown_size
    assert report.outline_savings()[0] == 0, "an image can never be outlined"
    assert "image" in report.biggest(1)[0].label


def test_duplicate_reads_are_detected(tmp_path):
    body = "def f():\n    return 1\n" * 50
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Read"),
            _result("t1", {"file": {"filePath": "/a/b.py", "content": body}}),
            _assistant("t2", "Read"),
            _result("t2", {"file": {"filePath": "/a/b.py", "content": body}}),
        ],
    )
    dupes = analyze([path]).duplicate_reads()
    assert len(dupes) == 1
    file_path, times, wasted = dupes[0]
    assert file_path == "/a/b.py" and times == 2 and wasted > 0


def test_a_changed_file_is_not_a_duplicate_read(tmp_path):
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Read"),
            _result("t1", {"file": {"filePath": "/a/b.py", "content": "one\n" * 50}}),
            _assistant("t2", "Read"),
            _result("t2", {"file": {"filePath": "/a/b.py", "content": "two\n" * 50}}),
        ],
    )
    assert analyze([path]).duplicate_reads() == []


def test_outline_savings_only_counts_code(tmp_path):
    """Skeletonising prose deletes it; counting that as a saving is dishonest."""
    prose = "Some explanation that matters.\n" * 200
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Read"),
            _result("t1", {"file": {"filePath": "/a/notes.md", "content": prose}}),
            _assistant("t2", "Read"),
            _result("t2", {"file": {"filePath": "/a/x.json", "content": "{}" * 500}}),
        ],
    )
    before, after, rows = analyze([path]).outline_savings()
    assert before == 0 and after == 0 and rows == []
    assert ".md" not in OUTLINE_SUFFIXES and ".json" not in OUTLINE_SUFFIXES


def test_outline_savings_reports_real_code_reductions(tmp_path):
    body = "def handler(req, timeout=1.0):\n" + "    work()\n" * 200
    path = _write(
        tmp_path,
        [
            _assistant("t1", "Read"),
            _result("t1", {"file": {"filePath": "/a/b.py", "content": body}}),
        ],
    )
    before, after, rows = analyze([path]).outline_savings()
    assert before > after > 0
    assert rows[0][0] == "/a/b.py"


def test_malformed_lines_are_skipped(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("not json\n" + json.dumps(_assistant("t", "Bash", {"output_tokens": 3})) + "\n")
    assert analyze([path]).usage["output_tokens"] == 3


def test_empty_transcript(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("")
    report = analyze([path])
    assert report.sessions == 1 and report.calls == []
    assert report.cache_hit_rate == 0.0


def test_project_slug_matches_claude_code_layout():
    assert project_slug("/home/u/proj") == "-home-u-proj"


def test_project_slug_replaces_every_non_alphanumeric_like_claude_code():
    # tempfile names such as /tmp/acco-e2e-m5_wfwlk/repo contain "_"
    assert (
        project_slug("/tmp/acco-e2e-m5_wfwlk/repo")
        == "-tmp-acco-e2e-m5-wfwlk-repo"
    )
    assert project_slug("/home/u/.config/my proj") == "-home-u--config-my-proj"


def test_transcript_paths_for_an_unknown_project(tmp_path, monkeypatch):
    monkeypatch.setattr("acco.sessions.projects_dir", lambda: tmp_path)
    assert transcript_paths(tmp_path / "nope") == []


def test_transcript_paths_scopes_to_one_project(tmp_path, monkeypatch):
    monkeypatch.setattr("acco.sessions.projects_dir", lambda: tmp_path)
    project = tmp_path / project_slug("/home/u/proj")
    project.mkdir()
    (project / "a.jsonl").write_text("")
    (tmp_path / "-other").mkdir()
    (tmp_path / "-other" / "b.jsonl").write_text("")
    assert [p.name for p in transcript_paths("/home/u/proj")] == ["a.jsonl"]
    assert len(transcript_paths(None, all_projects=True)) == 2


def _blocks(message_id, blocks, usage):
    """The real transcript shape: ONE api response written as one line per block.

    Claude Code repeats the identical `message.usage` on every one of those
    lines. A fixture that emits a single block per message cannot reproduce
    this, which is exactly how the overcount survived a green suite.
    """
    return [
        {
            "type": "assistant",
            "message": {"id": message_id, "usage": usage, "content": [block]},
        }
        for block in blocks
    ]


def test_usage_counted_once_per_api_response(tmp_path):
    usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 123_070,
        "cache_read_input_tokens": 0,
        "output_tokens": 400,
    }
    blocks = [
        {"type": "thinking"},
        {"type": "text"},
        {"type": "tool_use", "id": "a", "name": "Bash"},
        {"type": "tool_use", "id": "b", "name": "Bash"},
        {"type": "tool_use", "id": "c", "name": "Read"},
    ]
    path = _write(tmp_path, _blocks("msg_01", blocks, usage))
    report = analyze([path])

    assert report.fresh_input == 123_070, "billed once, not once per block"
    assert report.usage["output_tokens"] == 400
    assert len(report.turns) == 1


def test_distinct_responses_still_add_up(tmp_path):
    usage = {"cache_creation_input_tokens": 100, "cache_read_input_tokens": 50}
    records = _blocks("msg_01", [{"type": "text"}, {"type": "text"}], usage)
    records += _blocks("msg_02", [{"type": "text"}], usage)
    report = analyze([_write(tmp_path, records)])
    assert report.fresh_input == 200, "two responses, not one and not three"


def test_same_message_id_in_two_sessions_is_not_merged(tmp_path):
    """Dedup is per transcript; ids from different sessions are different turns."""
    usage = {"cache_creation_input_tokens": 100}
    a = _write(tmp_path, _blocks("msg_01", [{"type": "text"}], usage), name="a.jsonl")
    b = _write(tmp_path, _blocks("msg_01", [{"type": "text"}], usage), name="b.jsonl")
    assert analyze([a, b]).fresh_input == 200


def test_cache_churn_finds_cold_reprimes(tmp_path):
    cold = {"cache_creation_input_tokens": 200_000, "cache_read_input_tokens": 1_000}
    warm = {"cache_creation_input_tokens": 500, "cache_read_input_tokens": 190_000}
    records = _blocks("initial", [{"type": "text"}], cold)
    records += _blocks("msg_02", [{"type": "text"}], warm)
    records += _blocks("msg_03", [{"type": "text"}], cold)
    report = analyze([_write(tmp_path, records)])

    tokens, turns, worst = report.cache_churn()
    assert turns == 1, "only the cold re-prime counts"
    assert tokens == 189_500
    assert worst[0].read == 1_000


def test_growth_turn_is_not_churn(tmp_path):
    """Writing a little cache while reading a lot back is a cache hit, not churn."""
    usage = {
        "cache_creation_input_tokens": REPRIME_MIN_TOKENS + 1,
        "cache_read_input_tokens": REPRIME_MIN_TOKENS * 10,
    }
    report = analyze([_write(tmp_path, _blocks("m", [{"type": "text"}], usage))])
    assert report.cache_churn()[1] == 0

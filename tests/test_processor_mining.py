"""Tests for transcript-driven processor gap mining."""

from __future__ import annotations

import json

from acco.processor_mining import command_signature, mine_transcripts


def _write_pair(handle, uid: str, command: str, result: str) -> None:
    """Write one Claude Bash tool-use/result pair."""
    handle.write(json.dumps({
        "type": "assistant",
        "message": {
            "content": [{
                "type": "tool_use",
                "id": uid,
                "name": "Bash",
                "input": {"command": command},
            }]
        },
    }) + "\n")
    handle.write(json.dumps({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": uid}]},
        "toolUseResult": {"stdout": result, "stderr": "", "exitCode": 0},
    }) + "\n")


def test_command_signature_removes_argument_values():
    """Corpus reports should retain command families rather than raw arguments."""
    assert command_signature("TOKEN=secret sudo git log --author private") == "git log"
    assert command_signature("pnpm run integration -- --token secret") == "pnpm run integration"
    assert command_signature("python -m pytest private/test.py") == "python -m pytest"


def test_mining_prioritizes_high_token_generic_families(tmp_path):
    """Unsupported processor work should be ranked by real transcript token volume."""
    transcript = tmp_path / "session.jsonl"
    with transcript.open("w", encoding="utf-8") as handle:
        _write_pair(
            handle,
            "t1",
            "git status",
            "On branch main\n" + "\n".join(f" modified: src/{i}.py" for i in range(100)),
        )
        _write_pair(
            handle,
            "t2",
            "frobnicate --account private --verbose",
            "\n".join(f"opaque diagnostic payload {i} " + "x" * 80 for i in range(220)),
        )

    report = mine_transcripts([transcript], min_tokens=1, top=5)

    assert report["sessions"] == 1
    assert report["bash_calls"] == 2
    assert report["processor_tokens"]["git-status"] > 0
    assert report["generic_output_tokens"] > 0
    assert report["unsupported"][0]["signature"] == "frobnicate"
    assert "--account" not in json.dumps(report["unsupported"])
    assert report["specialized_coverage"] is not None

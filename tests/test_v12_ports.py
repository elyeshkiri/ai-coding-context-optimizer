import json

from token_saver.entry import main as entry_main
from token_saver.evaluate import ground_truth_hash
from token_saver.host_validate import _transport_roundtrip


def test_hook_transport_roundtrip_recovers_omitted_middle(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    result = _transport_roundtrip()
    assert result["ok"] is True
    assert result["recovery_verified"] is True
    assert result["replacement_lines"] < result["original_lines"]


def test_evaluate_cli_prints_portable_ground_truth_hash(tmp_path, capsys):
    manifest = tmp_path / "holdout.json"
    payload = {
        "suite_version": 1,
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
            "frozen_at": "2026-09-17T12:00:00Z",
            "ground_truth_sha256": "placeholder",
        },
        "repositories": {
            "app": {"path": "../app", "revision": "abc123"},
        },
        "tasks": [{
            "id": "auth",
            "repository": "app",
            "query": "refresh session",
            "files": ["src/auth.ts"],
            "symbols": ["refreshSession"],
        }],
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert entry_main([
        "evaluate", str(manifest), "--print-ground-truth-hash"
    ]) == 0
    assert capsys.readouterr().out.strip() == ground_truth_hash(payload)


def test_host_check_command_is_routed(monkeypatch, capsys, tmp_path):
    result = {
        "host": {"found": False},
        "project_settings": {},
        "user_settings": {},
        "configured": False,
        "hook_transport": {"ok": True},
        "live_host_evidence": {"provided": False, "accepted_replacement": None},
        "ready": False,
        "live_verified": False,
    }
    monkeypatch.setattr("token_saver.commands.validate_host", lambda *args, **kwargs: result)
    assert entry_main(["host-check", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["hook_transport"]["ok"] is True

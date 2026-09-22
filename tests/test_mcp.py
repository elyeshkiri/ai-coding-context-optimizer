"""Measuring MCP tool schemas instead of telling you to go look."""

import json
import sys
import textwrap

from acco.mcp import load_servers, probe, probe_all

FAKE_SERVER = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        try: m = json.loads(line)
        except Exception: continue
        if m.get("id") == 1:
            print(json.dumps({"jsonrpc":"2.0","id":1,"result":{}}), flush=True)
        if m.get("id") == 2:
            tools = [{"name": f"t{i}", "description": "x" * 120,
                      "inputSchema": {"type": "object"}} for i in range(5)]
            print(json.dumps({"jsonrpc":"2.0","id":2,
                              "result":{"tools":tools}}), flush=True)
            break
    """
)


def _project(tmp_path, servers):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": servers}))
    return tmp_path


def test_a_stdio_server_is_measured(tmp_path):
    (tmp_path / "server.py").write_text(FAKE_SERVER)
    root = _project(tmp_path, {"local": {"command": sys.executable, "args": ["server.py"]}})
    cost = probe_all(root)[0]
    assert cost.status == "measured"
    assert cost.tools == 5
    assert cost.tokens and cost.tokens > 0


def test_server_commands_run_from_the_project_root(tmp_path):
    """Regression: found live — the server inherited acco's cwd, not the
    project's, so a relative command in .mcp.json could not be found."""
    (tmp_path / "server.py").write_text(FAKE_SERVER)
    root = _project(tmp_path, {"local": {"command": sys.executable, "args": ["server.py"]}})
    assert probe("local", {"command": sys.executable, "args": ["server.py"]},
                 cwd=root).status == "measured"
    assert probe("local", {"command": sys.executable, "args": ["server.py"]},
                 cwd=None).status != "measured"


def test_a_remote_server_is_reported_not_probed(tmp_path):
    root = _project(tmp_path, {"api": {"type": "http", "url": "https://x/mcp"}})
    cost = probe_all(root)[0]
    assert not cost.measured and "remote" in cost.status


def test_a_missing_binary_is_reported_cleanly(tmp_path):
    root = _project(tmp_path, {"gone": {"command": "definitely-not-a-real-binary"}})
    cost = probe_all(root)[0]
    assert not cost.measured and "not found" in cost.status


def test_a_hanging_server_times_out(tmp_path):
    (tmp_path / "hang.py").write_text("import time\ntime.sleep(30)\n")
    root = _project(tmp_path, {"slow": {"command": sys.executable, "args": ["hang.py"]}})
    cost = probe("slow", {"command": sys.executable, "args": ["hang.py"]},
                 timeout=2, cwd=root)
    assert not cost.measured and "timed out" in cost.status


def test_a_server_that_says_nothing_is_reported(tmp_path):
    (tmp_path / "mute.py").write_text("import sys\nsys.stdin.read()\n")
    root = _project(tmp_path, {"mute": {"command": sys.executable, "args": ["mute.py"]}})
    cost = probe("mute", {"command": sys.executable, "args": ["mute.py"]},
                 timeout=5, cwd=root)
    assert not cost.measured and "no tools/list" in cost.status


def test_config_loading(tmp_path):
    root = _project(tmp_path, {"a": {"command": "x"}, "b": {"command": "y"}})
    assert sorted(load_servers(root)) == ["a", "b"]


def test_malformed_config_is_ignored(tmp_path):
    (tmp_path / ".mcp.json").write_text("{ not json")
    assert load_servers(tmp_path) == {}


def test_no_config_at_all(tmp_path):
    assert load_servers(tmp_path) == {} and probe_all(tmp_path) == []

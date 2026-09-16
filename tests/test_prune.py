from token_saver.prune import unused_servers, used_server_names
from token_saver.sessions import Report, ToolCall


def test_unused_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"github": {"command": "npx"}, "docs": {"command": "npx"}}}\n'
    )
    report = Report()
    report.calls.append(ToolCall(name="mcp__github__search", tokens=10, session="s"))
    unused = unused_servers(tmp_path, report)
    assert unused == ["docs"]
    assert "github" in used_server_names(report)

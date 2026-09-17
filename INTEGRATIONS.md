# Agent integrations

Install Token Saver in the environment that launches the coding agent:

```bash
python -m pip install .
```

The MCP process is local and uses newline-delimited JSON-RPC over stdio:

```bash
token-saver serve /absolute/path/to/project
```

Copy the relevant example from `integrations/` into the agent's project or user
configuration. Replace `.` with an absolute project path when the agent launches
MCP servers from another working directory.

Available MCP tools:

- `build_context`
- `find_symbol`
- `analyze_change_impact`
- `build_diff_context`
- `review_diff`
- `report_context_feedback`
- `index_status`
- `refresh_index`

Call `refresh_index` after external file changes when a long-running server must
see the new source immediately. Context generation otherwise reuses the current
in-memory snapshot for predictable low latency.

The GitHub Actions example is intentionally a reporting/validation workflow. It
does not modify a pull request or publish benchmark claims.

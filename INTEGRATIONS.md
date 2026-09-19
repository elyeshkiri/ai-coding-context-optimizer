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


## Claude Code output optimization

Install the hooks after installing or upgrading Token Saver:

```bash
token-saver install /absolute/path/to/project --templates
```

For a user-wide hook installation:

```bash
token-saver install . --user
```

The Claude Code integration uses two distinct boundaries:

- `PreToolUse` protects against unbounded large source reads and lone
  `cat <large-source>` dumps;
- `PostToolUse` can reduce large Bash stdout through the failure-aware output
  processor registry while keeping the original result recoverable locally.

Inspect which processor would handle a command:

```bash
token-saver output-explain "pytest -q"
token-saver output-explain "npm install" --exit-code 1
```

Graph-aware diagnostic Delta is opt-in:

```bash
export TOKEN_SAVER_DELTA=1
```

It currently applies to supported repeated pytest and Ruff diagnostics within a
Claude Code session. See [OUTPUT_OPTIMIZATION.md](OUTPUT_OPTIMIZATION.md) for
failure routing, critical-line recovery, quality replay, Delta state, and graph
mapping details.

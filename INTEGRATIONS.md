# Agent integrations

Install Token Saver in the environment that launches the coding agent, then let
the setup command detect and configure supported hosts:

```bash
pip install claude-token-saver
cd /absolute/path/to/project
token-saver setup
token-saver doctor
```

Supported automatic setup currently covers:

- **Claude Code** — project hooks plus project MCP configuration;
- **Cursor** — project `.cursor/mcp.json`;
- **Codex** — a clearly marked Token Saver block in the user Codex TOML config.

Only Token Saver-owned entries are changed. Setup is idempotent, so rerunning it
after upgrades repairs/migrates managed entries without duplicating them.
`token-saver uninstall` reverses those entries while preserving unrelated host
configuration.

Use `--host claude|cursor|codex|all` for explicit selection. The files under
`integrations/` remain manual fallback/reference templates.

The MCP process is local and uses newline-delimited JSON-RPC over stdio:

```bash
token-saver serve /absolute/path/to/project
```

Available MCP tools:

- `build_context`
- `find_symbol`
- `analyze_change_impact`
- `build_diff_context`
- `review_diff`
- `report_context_feedback`
- `index_status`
- `refresh_index`
- `output_policy`
- `compact_output`

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

The Claude Code integration uses four distinct boundaries:

- `UserPromptSubmit` automatically selects and injects a generation-time output
  policy when the task/mode changes, so completion tokens can be avoided before
  they are generated;
- `PreToolUse` protects against unbounded large source reads and lone
  `cat <large-source>` dumps;
- `PostToolUse` can reduce large Bash stdout through the failure-aware output
  processor registry, collapse exact repeated command output, and observe
  Read/Edit/Write working-state changes while keeping replaced Bash output
  recoverable locally;
- `SessionStart` resume/compact can inject a bounded structured continuity
  checkpoint containing working files, redacted recent commands, and validation
  status without copying conversation text;
- `Stop` and `StopFailure` read the current turn's appended transcript usage
  counters and record content-free budget telemetry locally.

The prompt classifier is deterministic and conservative. Ambiguous follow-ups
inherit the current session policy without another full policy injection.
`clear`/compaction session events reset the remembered policy because the host
may have rebuilt context. User prompt text is not persisted by this feature. Adaptive budgeting changes
the token target only when a task/mode/new-task signal warrants recalculation;
vague follow-ups keep the current budget exactly. If a quality-gated calibration
artifact is present, its task/mode recommendation becomes the learned base.
Claude's documented per-turn `Stop` event supplies the transcript path used for
measurement; Token Saver never persists the hook's `last_assistant_message`.

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


## Project configuration

Setup creates `.token-saver.toml`. The nearest file is discovered by walking
from the active project directory toward the filesystem root. Environment
variables override the TOML values for temporary/CI changes.

```toml
version = 1

[hooks]
guard = true
read_max_lines = 220
reread = false
delta = false
min_lines = 40
keep_tail = 15
allow = []

[output]
enabled = true
mode = "normal"
task = "auto"
adaptive = true
calibration_file = ".token-saver.output-calibration.json"
telemetry = true

[efficiency]
enabled = true
continuity = true
dedup = true
waste_detection = true
```

Automatic generation-policy injection currently uses Claude Code's prompt hook.
Cursor and Codex still receive the same policy through the `output_policy` MCP
tool when an orchestrator chooses to call it.

## Troubleshooting and repair

```bash
token-saver doctor .
token-saver doctor . --json
token-saver setup .        # idempotent repair / upgrade migration
token-saver commands
```

For Claude Code, the existing lower-level `token-saver host-check` remains
available when you need transport/live-host evidence beyond the consolidated
configuration health report.

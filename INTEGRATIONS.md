# Agent integrations

Install Token Saver in the environment that launches the coding agent, then let
the setup command detect and configure supported hosts:

```bash
pip install claude-token-saver
cd /absolute/path/to/project
token-saver setup
token-saver doctor
```

## Claude Code marketplace install

Claude-only users on Claude Code **2.1.229+** can install through the repository
marketplace without first placing the `token-saver` console script on `PATH`:

```text
/plugin marketplace add elyeshkiri/token-saver
/plugin install token-saver@token-saver-tools
```

The marketplace uses Claude Code's command-source installation flow. Claude
shows the bootstrap command for user approval before it runs. The command
installs the current GitHub package quietly, then prints the one absolute plugin
directory produced by `token-saver claude-plugin-path`.

The generated plugin owns only its own plugin directory and invokes Token Saver
as `python -m token_saver.entry`. It includes:

- the normal PreToolUse/PostToolUse/SessionStart/UserPromptSubmit/Stop hooks;
- the local Token Saver MCP server;
- `/token-saver:ingress <stage-id>` for resuming a safely staged oversized prompt.

For Cursor, Codex, mixed-host projects, editable installs, or environments where
you want explicit project config management, continue to use pip +
`token-saver setup`.

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

The default `full` profile exposes repository context, ranking/impact,
semantic-index, patch review, output policy, model routing, and persistent-memory
tools. Persistent memory uses a progressive contract:

- `memory_index` — compact ids/claims/types/scores;
- `memory_search` — bounded snippets for relevance confirmation;
- `memory_get` — full records by selected id;
- `remember_memory` — typed evidence-backed project memory.

Existing `remember_finding`, `recall_findings`, and `knowledge_status`
remain supported.

For lower recurring tool-schema cost, set `[mcp] profile = "adaptive"` in
`.token-saver.toml` or export `TOKEN_SAVER_MCP_PROFILE=adaptive`. The initial
surface stays small and includes `discover_tools` plus exact
`recover_context`; a discovery call selects bounded specialist groups for the
current task, returns their exact schemas, and replaces the specialist portion
of subsequent `tools/list` responses.

Set `mcp.compress_schemas = true` to additionally remove annotation-only
schema metadata and shorten long descriptions conservatively. When compression
is beneficial, the exact original catalog is stored under a `tsr_...` recovery
handle. Set `profile = "full"` and/or `compress_schemas = false` as the
compatibility fallback for hosts with limited dynamic-tool support.

Call `refresh_index` after external file changes when a long-running server must
see the new source immediately. Context generation otherwise reuses the current
in-memory snapshot for predictable low latency.

The GitHub Actions example is intentionally a reporting/validation workflow. It
does not modify a pull request or publish benchmark claims.


## Provider base-URL integration

The v1.13 provider proxy is separate from Claude/Cursor/Codex managed setup. It
is an explicit local reverse proxy for clients that can choose their API base
URL:

```bash
token-saver provider-proxy . \
  --provider anthropic \
  --upstream https://api.anthropic.com
```

Point the client at the printed loopback URL using that client's supported
base-URL setting. Token Saver does not rewrite host configuration to enable the
proxy automatically.

The proxy can combine recoverable tool-schema compression, large historical
tool-result compression, captured browser-context focusing, and stable-prefix
reuse accounting before the request reaches the configured upstream. Provider
responses are forwarded unchanged. Non-local plaintext upstreams, embedded URL
credentials, cross-origin absolute-form targets, and automatic redirect
following are refused by design.

Use:

```bash
token-saver prefix-status .
token-saver recovery-status .
```

to inspect content-free prefix evidence and recovery capacity. See
[Security & privacy](SECURITY.md) before enabling this network boundary.

## Claude Code output optimization

Install the hooks after installing or upgrading Token Saver:

```bash
token-saver install /absolute/path/to/project --templates
```

For a user-wide hook installation:

```bash
token-saver install . --user
```

The Claude Code integration uses five distinct boundaries:

- `UserPromptSubmit` automatically selects and injects a generation-time output
  policy when the task/mode changes, so completion tokens can be avoided before
  they are generated;
- `PreToolUse` protects against unbounded large source reads and lone
  `cat <large-source>` dumps; when the opt-in Smart Tool Proxy is enabled,
  eligible large Reads are delegated to PostToolUse instead of denied;
- `PostToolUse` can reduce large Bash stdout through the failure-aware output
  processor registry, collapse exact repeated command output, and replace an
  eligible full-file Read with local/free-model-guided **exact source ranges**.
  Selector-generated prose is not forwarded; delivered code is re-read from
  the source file, and bounded Reads remain untouched for edit-grade bytes;
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

[model_routing]
enabled = false
mode = "advisory"
current_model = ""
allowed_models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]
min_savings = 0.05
conservative = true
calibration_file = ".token-saver.routing-calibration.json"

[efficiency]
enabled = true
continuity = true
dedup = true
waste_detection = true

[ingress]
enabled = false
threshold_tokens = 12000
packet_tokens = 1600

[retrieval]
cache = true
cache_max_entries = 64

[mcp]
profile = "full"
adaptive_max_tools = 12
compress_schemas = false

[provider]
prefix_tracking = true

[tool_proxy]
enabled = false
provider = "ollama"
model = "qwen2.5-coder:7b"
endpoint = "http://127.0.0.1:11434"
min_tokens = 2500
target_tokens = 1800
model_input_tokens = 12000
timeout_seconds = 6.0
max_ranges = 4
max_range_lines = 80
```

Automatic generation-policy injection currently uses Claude Code's prompt hook.
Cursor and Codex still receive the same policy through the `output_policy` MCP
tool when an orchestrator chooses to call it.

Automatic model routing is opt-in. When enabled, Token Saver classifies the task,
derives a complexity/risk capability floor, then chooses the cheapest eligible
model from the freshness-gated pricing registry. Claude Code's prompt hook can
record and inject the decision but cannot replace the active top-level model.
Model-selectable orchestrators should call the MCP `route_task` tool and execute
its `selected_model` / `action` decision directly. The default capability
profiles are conservative product policy, not model-quality benchmark results.

A quality-gated calibration artifact may admit a cheaper model outside the
static capability profile for one exact bucket. Generate that artifact only
from paired arms that differ by model choice alone, after independent
verification and `blind-grade`:

```bash
token-saver experiment routing-suite.json --out routing-runs.json
token-saver blind-grade routing-runs.json
token-saver model-route-calibrate routing-runs.json
```

The runtime rechecks hard evidence floors before using any recommendation.
Invalid calibration falls back to the static conservative router.

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

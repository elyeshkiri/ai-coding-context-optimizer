# Configuration

Token Saver has two configuration layers:

1. the nearest project `.token-saver.toml`;
2. `TOKEN_SAVER_*` environment variables, which override project values.

Host integration files are managed separately by `token-saver setup`.

## Project config discovery

Starting from the active repository path, Token Saver walks toward the
filesystem root and loads the nearest `.token-saver.toml`.

A default file created by `token-saver setup` is:

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
knowledge_read_avoidance = false
cache_economics = false
cache_expected_reuses = 2
cache_write_factor = 1.25
cache_read_factor = 0.10
cache_min_relative_savings = 0.05
```

## Hook settings

| TOML key | Default | Meaning |
|---|---:|---|
| `hooks.guard` | `true` | Enable the large source Read/`cat` guard. |
| `hooks.read_max_lines` | `220` | Maximum unbounded source read before guarding. |
| `hooks.reread` | `false` | Block unchanged repeated full reads in a session. |
| `hooks.delta` | `false` | Enable graph-aware diagnostic Delta where supported. |
| `hooks.min_lines` | `40` | Minimum Bash output size before normal compression is considered. |
| `hooks.max_lines` | unset | Explicit retained-line cap; otherwise Token Saver derives one. |
| `hooks.keep_tail` | `15` | Tail lines retained by output compaction. |
| `hooks.allow` | `[]` | Filename, absolute-path, or repository-relative guard globs. |
| `hooks.disabled` | `false` | Disable Token Saver hook behavior without uninstalling it. |

## Generation output policy

Claude Code's `UserPromptSubmit` hook can automatically classify the current
task and inject the generation-time response policy before the model answers.
The classifier is deterministic and conservative: strong debugging/review/
coding/planning/explanation language selects a task class, while ambiguous
follow-ups inherit the current session class without another policy injection.

| TOML key | Default | Meaning |
|---|---:|---|
| `output.enabled` | `true` | Enable automatic generation-policy injection where the host supports prompt hooks. |
| `output.mode` | `"normal"` | Default response mode: `terse`, `normal`, or `detailed`. |
| `output.task` | `"auto"` | Task policy: `auto`, `general`, `coding`, `debugging`, `review`, `explanation`, or `planning`. |
| `output.adaptive` | `true` | Scale the task/mode base budget using deterministic prompt-complexity signals. |
| `output.min_tokens` | unset | Optional project floor for adaptive budgets, still bounded by the selected mode's safety range. |
| `output.max_tokens` | unset | Optional project ceiling for adaptive budgets, still bounded by the selected mode's safety range. |
| `output.calibration_file` | `".token-saver.output-calibration.json"` | Optional learned-budget artifact produced by `output-calibrate`; missing/invalid files fall back to built-in bases. |
| `output.telemetry` | `true` | Record local content-free turn usage at Claude `Stop`/`StopFailure` for budget-effectiveness reporting. |

The full policy is injected only when the resolved task/mode changes, on the
first prompt in a session, or after a clear/compact context reset. Token Saver
stores only the resolved task, mode, and budget in local session state; it does
not persist the user prompt for this feature. Explicit requests such as
"keep it short" or "give a comprehensive explanation" override the configured
mode for the active task.

Adaptive budgets use only visible prompt structure: request length, multi-part
lists, code/diagnostic evidence, and broad repository/architecture scope. A
vague follow-up inherits the current budget exactly instead of being rescored.
Built-in mode safety bounds prevent unbounded expansion or collapse. When a
valid calibration artifact is present, its quality-verified task/mode budget
becomes the learned base before complexity scaling.

With telemetry enabled, the Claude prompt hook checkpoints only the transcript
byte offset and resolved policy metadata. The `Stop`/`StopFailure` hook then
reads only transcript bytes appended during that turn and stores usage counters
plus policy metadata under the private Token Saver state directory. Prompt text,
assistant text, tool payloads, and transcript content are not copied into the
telemetry log. Disable temporarily with
`TOKEN_SAVER_OUTPUT_TELEMETRY=0`.

Example allowlist:

```toml
[hooks]
allow = ["generated/*", "*.gen.ts", "vendor/special.py"]
```

## Session efficiency

The efficiency layer is local, bounded, and independent from repository ranking.
It observes host hook events but never copies raw user prompts, assistant
responses, or tool output into its continuity snapshot.

| TOML key | Default | Meaning |
|---|---:|---|
| `efficiency.enabled` | `true` | Master switch for continuity, dedup evidence, and behavior tracking. |
| `efficiency.continuity` | `true` | Restore structured working-state orientation on Claude resume/compact events. |
| `efficiency.dedup` | `true` | Collapse exact repeated Bash output and block unchanged repeated full-file Reads. |
| `efficiency.waste_detection` | `true` | Surface bounded repeated-command, identical-failure retry-loop, and no-edit tool-cascade signals. |
| `efficiency.knowledge_read_avoidance` | `false` | Opt in to replacing full-file Reads with current verified findings anchored to that exact source file. Stale/non-verified findings never block reads. |
| `efficiency.cache_economics` | `false` | Require the cache-aware relative-cost policy to approve knowledge read avoidance. |
| `efficiency.cache_expected_reuses` | `2` | Expected later cache reads used by the relative-cost model. |
| `efficiency.cache_write_factor` | `1.25` | Relative cache-write input cost used for planning; override for the active provider/model. |
| `efficiency.cache_read_factor` | `0.10` | Relative cache-read input cost used for planning; override for the active provider/model. |
| `efficiency.cache_min_relative_savings` | `0.05` | Minimum projected lifetime input-cost reduction required when cache economics is enabled. |

Continuity stores only task class, working file paths, bounded redacted command
labels/fingerprints, validation outcomes, failure fingerprints, and counters.
Command labels apply best-effort credential redaction before persistence.
Original compressed Bash output continues to use Token Saver's separate private
recoverable-output store.

`/clear` resets the active working checkpoint. `/compact` and resume retain
the structured working set but reset transient per-turn counters. Cross-turn
dedup never substitutes approximate output: it requires the same normalized
command and exact output digest.

Knowledge-assisted read avoidance is disabled by default while its frozen
end-to-end holdout remains unexecuted. When enabled, it only considers
`verified`, non-stale findings whose anchors match the exact requested file.
The replacement must save at least a bounded token floor; if cache economics is
also enabled it must additionally clear the configured projected-cost threshold.
The model can always request a bounded `Read` range when exact implementation
bytes are needed.

## Environment overrides

Environment variables take precedence over TOML:

| Variable | Project equivalent |
|---|---|
| `TOKEN_SAVER_DISABLED` | `hooks.disabled` |
| `TOKEN_SAVER_GUARD` | `hooks.guard` |
| `TOKEN_SAVER_READ_MAX_LINES` | `hooks.read_max_lines` |
| `TOKEN_SAVER_REREAD` | `hooks.reread` |
| `TOKEN_SAVER_ALLOW` | `hooks.allow` (colon-separated) |
| `TOKEN_SAVER_DELTA` | `hooks.delta` |
| `TOKEN_SAVER_MIN_LINES` | `hooks.min_lines` |
| `TOKEN_SAVER_MAX_LINES` | `hooks.max_lines` |
| `TOKEN_SAVER_KEEP_TAIL` | `hooks.keep_tail` |
| `TOKEN_SAVER_OUTPUT_POLICY` | `output.enabled` |
| `TOKEN_SAVER_OUTPUT_MODE` | `output.mode` |
| `TOKEN_SAVER_OUTPUT_TASK` | `output.task` |
| `TOKEN_SAVER_OUTPUT_ADAPTIVE` | `output.adaptive` |
| `TOKEN_SAVER_OUTPUT_MIN_TOKENS` | `output.min_tokens` |
| `TOKEN_SAVER_OUTPUT_MAX_TOKENS` | `output.max_tokens` |
| `TOKEN_SAVER_OUTPUT_CALIBRATION_FILE` | `output.calibration_file` |
| `TOKEN_SAVER_OUTPUT_TELEMETRY` | `output.telemetry` |
| `TOKEN_SAVER_EFFICIENCY` | `efficiency.enabled` |
| `TOKEN_SAVER_CONTINUITY` | `efficiency.continuity` |
| `TOKEN_SAVER_CROSS_TURN_DEDUP` | `efficiency.dedup` |
| `TOKEN_SAVER_WASTE_DETECTION` | `efficiency.waste_detection` |
| `TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE` | `efficiency.knowledge_read_avoidance` |
| `TOKEN_SAVER_CACHE_ECONOMICS` | `efficiency.cache_economics` |
| `TOKEN_SAVER_CACHE_EXPECTED_REUSES` | `efficiency.cache_expected_reuses` |
| `TOKEN_SAVER_CACHE_WRITE_FACTOR` | `efficiency.cache_write_factor` |
| `TOKEN_SAVER_CACHE_READ_FACTOR` | `efficiency.cache_read_factor` |
| `TOKEN_SAVER_CACHE_MIN_RELATIVE_SAVINGS` | `efficiency.cache_min_relative_savings` |

Boolean overrides accept `1/true/yes/on`; other values resolve to false.

Example temporary override:

```bash
TOKEN_SAVER_DELTA=1 TOKEN_SAVER_READ_MAX_LINES=150 claude

# Disable automatic generation-policy injection temporarily:
TOKEN_SAVER_OUTPUT_POLICY=0 claude

# Force a fixed terse review policy instead of auto-classification:
TOKEN_SAVER_OUTPUT_MODE=terse TOKEN_SAVER_OUTPUT_TASK=review claude
```

## Managed host files

### Claude Code

Setup manages:

- `.claude/settings.json`: only hook commands equal to `token-saver hook`;
- `.mcp.json`: only `mcpServers.token-saver`;
- `.claude/skills/token-budget/SKILL.md`: generated template.

Uninstall removes the generated skill only if it is still byte-identical to the
Token Saver template. A user-edited skill is preserved.

### Cursor

Setup manages only:

```text
.cursor/mcp.json → mcpServers.token-saver
```

Other MCP servers remain untouched.

### Codex

Setup manages only the block between:

```toml
# >>> token-saver managed >>>
...
# <<< token-saver managed <<<
```

If an unmanaged `[mcp_servers.token-saver]` already exists, setup refuses to
overwrite it.

## Mutation safety

For multi-host setup, Token Saver preflights every selected managed file before
the first write. Invalid JSON or a conflicting Codex block therefore fails
before any earlier host is partially configured.

All JSON writes are atomic.

## State and saved output

Session state defaults to:

```text
~/.claude/token-saver/
```

Override it with:

```bash
export TOKEN_SAVER_STATE_DIR=/another/private/path
```

Saved original command output is local and can be paged with `token-saver
output` or pruned with `token-saver outputs-prune`.

See [Security & privacy](../SECURITY.md) for persistence boundaries.

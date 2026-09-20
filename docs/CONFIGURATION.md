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

The full policy is injected only when the resolved task/mode changes, on the
first prompt in a session, or after a clear/compact context reset. Token Saver
stores only the resolved task, mode, and budget in local session state; it does
not persist the user prompt for this feature. Explicit requests such as
"keep it short" or "give a comprehensive explanation" override the configured
mode for the active task.

Example allowlist:

```toml
[hooks]
allow = ["generated/*", "*.gen.ts", "vendor/special.py"]
```

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

# Token Saver 1.0.0

Token Saver is a local context-optimization layer for AI coding agents. It reduces unnecessary source, tool-output, and always-on context while preserving exact code where the model needs it.

The project is deliberately conservative: **smaller context is useful only when the task still succeeds**. Token Saver does not claim a universal percentage reduction in task cost. It measures input size, preserves diagnostics, and keeps omitted command output recoverable.

## What is new in 1.0

Token Saver now compiles both tasks and patches into bounded, explainable context:

```bash
# Task-aware context with exact symbol bodies and dependency closure
token-saver pack . -q "fix session refresh" --closure-items 20 --max-tokens 6000

# Context surrounding the current patch
token-saver pack-diff . --base HEAD --max-tokens 6000

# Changed symbols, callers, API changes, test signals, and affected files
token-saver review . --base HEAD --json
```

v1.0 adds:

- bounded dependency closure with source edge, distance, and confidence;
- Tree-sitter-backed exact symbol ranges for JavaScript, TypeScript, JSX, and TSX;
- patch-aware context generation and deterministic review signals;
- public-signature change, removed-symbol, and missing-test detection;
- a persistent MCP index service with status and incremental refresh tools;
- MCP tools for task context, diff context, symbol search, impact, review, and feedback;
- paired agent-outcome evaluation that suppresses savings claims when quality falls;
- ready-to-copy Codex, Claude Code, Cursor, and GitHub Actions integrations.

The included deterministic benchmark currently measures **88% relevant-file
recall, 92% relevant-symbol recall, and 93.68% mean estimated context
reduction** at a 6,000-token cap. These are retrieval measurements, not an
end-to-end claim about agent success. (The 1.0.0 release measured 96%/100%/92.94%
on this repository at that commit; see CHANGELOG.md. Numbers move slightly as
the tool's own source -- part of the benchmark corpus -- changes; re-run
`token-saver evaluate` for the exact figure on your checkout.)

For paired real-agent outcomes:

```bash
token-saver agent-evaluate benchmarks/agent-runs.example.json
```

The evaluator reports a token-per-success reduction only when the Token Saver
condition preserves baseline success rate.

### Evidence coverage beyond source code (unreleased)

`pack-diff`/`review` used to see only source files. The index now also
covers SQL migrations, `package.json`, CI workflows
(`.github/workflows/*.yml`), and `.env.example`-style templates -- each with
real extracted symbols (table names, npm scripts, CI job ids, env vars)
reusing the same symbol/call-graph machinery as functions and classes,
rather than a separate subsystem. A file that carries real regression risk
but would otherwise lose the ranking competition to a large newly-added file
(a migration landing next to a big new feature, say) gets a small,
budget-capped guaranteed allocation instead of being silently dropped.

```bash
token-saver pack-diff . --base main --max-tokens 6000 --json
```

The JSON output includes a `coverage` field distinguishing selected,
closure-only, policy-excluded, and simply-didn't-fit files, and the
non-JSON output prints a one-line summary:

```text
# coverage: 12/129 changed files represented (110 not selected, 0 excluded by policy)
```

Validated end-to-end against a real 129-file diff from a separate
production application (private, not included in this repository): at a
fixed 4,000-token budget, an isolated reviewing model with no repository
access went from recovering roughly 5-7 of 15 independently-defined
ground-truth concerns to roughly 12-13 of 15 -- including two findings a
much larger (100,416-token, full-repository-access) baseline review missed
-- while token cost stayed within about 1% of the pre-widening figure. This
is a single diff, not a statistically validated benchmark; see
[CHANGELOG.md](CHANGELOG.md) for full methodology and the checked-in
regression fixture that guards the result going forward.

## What was new in 0.9

### Evaluation-driven symbol context

v0.9 upgrades the file-level index into a symbol graph. Python definitions carry
exact ranges, signatures, parent classes, and calls; other languages retain a
conservative declaration index. Context packs prefer complete symbol bodies and
still enforce the hard token cap.

```bash
token-saver pack . -q "session refresh bug" \
  --target-symbol refresh_session --max-tokens 4000 --json

token-saver impact refresh_session --path . --json
```

The release adds:

- exact symbol-level packing with selected-symbol metadata;
- file/symbol change-impact analysis across imports, calls, and related tests;
- bounded, inspectable local feedback via `token-saver feedback`;
- a ground-truth evaluator reporting file recall, symbol recall, and token reduction;
- an included 25-task benchmark manifest in `benchmarks/context-quality.json`;
- a native stdio MCP server with context, symbol, impact, and feedback tools;
- sensitive-path rejection, symlink containment, and inline secret redaction;
- structured JSON output for agent integrations.

Run the reproducible selector benchmark:

```bash
token-saver evaluate benchmarks/context-quality.json --path . --max-tokens 6000
```

Run Token Saver as an MCP server:

```json
{
  "mcpServers": {
    "token-saver": {"command": "token-saver", "args": ["serve", "."]}
  }
}
```

Feedback is explicit, bounded, local, and never replaces deterministic relevance:

```bash
token-saver feedback src/auth/session.py --path . --useful
token-saver feedback src/legacy/auth.py --path . --irrelevant
```

## What was new in 0.8

### Incremental context compiler

The packer now maintains a content-addressed repository index and expands the
lexical result through import and symbol-call relationships. Unchanged files are
reused on the next run; edits invalidate only their own records.

```bash
token-saver pack . \
  -q "fix session refresh after logout" \
  --graph-hops 1 \
  --session auth-issue-42 \
  --max-tokens 6000 \
  --explain
```

v0.8 adds:

- incremental SHA-256-indexed symbol, import, call, and identifier extraction;
- dependency/call-graph expansion with distance-decayed ranking boosts;
- identifier-based near-duplicate suppression before spending context tokens;
- opt-in task/session working-set memory for related follow-up prompts;
- optional local embedding reranking with deterministic ranking as the default;
- atomic local state writes and explicit controls for cache, graph depth, and
  duplicate thresholds.

Session memory is enabled only with `--session`. A prior working set receives a
boost only when the next query overlaps the prior task terms. Repository index
and session state live under `TOKEN_SAVER_STATE_DIR` (or the existing default
state directory); neither source nor queries leave the machine.

Embedding reranking is optional and requires an already-downloaded local model:

```bash
pip install 'token-saver[embeddings]'
token-saver pack . -q "retry failed downloads" --embeddings
```

Token Saver requests the local `all-MiniLM-L6-v2` model with offline loading.
If it is unavailable, the command fails with an actionable message instead of
silently accessing a network or changing ranking behavior.

### Task-aware context packing

Instead of dumping a repository or relying on a static code map, Token Saver can build a context pack for the task you are actually working on:

```bash
token-saver pack . \
  --query "fix session refresh after logout" \
  --max-tokens 6000 \
  --explain
```

The packer:

- scans source files while respecting Git ignore rules;
- ranks files with dependency-free BM25-style lexical relevance;
- gives extra weight to path and symbol/API matches;
- boosts files currently changed in Git;
- uses structural source priority as a fallback for vague tasks;
- includes compact outlines for navigation;
- includes **exact line-numbered source windows** around the best matches;
- deduplicates selected sections;
- enforces a hard estimated-token budget;
- can explain why every candidate was ranked where it was.

This is the highest-leverage path for large repositories: spend the context window on code related to the current task instead of on whatever file happened to be read first.

Examples:

```bash
# 4k-token context pack for a bug
token-saver pack . -q "map contact button disappears on mobile" --max-tokens 4000

# save the pack
token-saver pack . -q "redis delayed notification consumer" -o CONTEXT.md

# inspect ranking decisions
token-saver pack . -q "authentication refresh token" --explain

# standalone executable, useful in scripts
token-saver-pack . -q "authentication refresh token" --max-tokens 3000
```

`--target-symbol`, `--json`, `--max-files`, `--context-lines`, `--graph-hops`, `--duplicate-threshold`,
`--session`, `--no-index-cache`, `--no-gitignore`, and `--no-changed-boost`
provide tighter control.

## Automatic protections

Install the Claude Code hooks:

```bash
python -m pip install .
token-saver install /path/to/project --templates
```

For user-wide installation:

```bash
token-saver install . --user
```

### Bounded source reads

A full `Read` of a large source file is denied before it enters context. The denial contains a capped structural outline with line-number gutters so the agent can request an exact range instead.

This happens before the read rather than rewriting its result: editing tools need the original source bytes.

```text
large full read
    ↓
PreToolUse guard
    ↓
outline + exact ranges
    ↓
bounded Read
```

Duplicate-read blocking is optional and off by default.

### Recoverable command-output compression

Large successful Bash output is compressed only when the replacement is materially smaller. Token Saver now also collapses long runs of identical successful log lines while retaining the repetition count.

Errors, exceptions, tracebacks, failed assertions, interrupted commands, images, unsupported structured responses, and stderr are treated conservatively. Test failures preserve diagnostic evidence.

Before replacing output, Token Saver stores the original result locally. The model receives a retrieval command instead of being forced to rerun the command:

```bash
token-saver output OUTPUT_ID --stream stdout --offset 1 --limit 80
```

Prune old originals explicitly:

```bash
token-saver outputs-prune --days 7
```

## Source navigation

```bash
# signatures/structure of one file
token-saver outline src/service.ts

# exact body of one symbol
token-saver snippet src/service.ts Service.fetchUser

# bounded structural map of a repo
token-saver map src --max-tokens 4000 -o CODEMAP.md

# task-aware working set
token-saver pack . -q "implement retry backoff for downloads" --max-tokens 5000
```

Python is parsed with `ast`. JavaScript, JSX, TypeScript, and TSX use Tree-sitter for structural extraction. Other supported languages retain conservative pattern-based outlines.

## Measure before claiming savings

Token Saver separates observed API usage from offline estimates:

```bash
token-saver sessions /path/to/project
token-saver policy /path/to/project
token-saver audit /path/to/project
token-saver budget /path/to/project
token-saver check /path/to/project
```

Reports distinguish recorded usage, cache reads/writes, repeated reads, estimated tool-result size, always-on instructions, MCP schema cost, and hypothetical one-shot outline reductions.

For paired real-task benchmarking:

```bash
token-saver benchmark runs.json --rates rates.json
```

See [BENCHMARKING.md](BENCHMARKING.md). A smaller prompt or tool result is not automatically a cheaper successful task; follow-up reads, retries, model quality, and cache behavior all matter.

## Context audit and MCP cost

```bash
token-saver audit .
token-saver audit . --probe-mcp
token-saver mcp-prune .
```

The audit identifies instructions and rules that are injected repeatedly, and can measure MCP tool-schema payloads. `mcp-prune` is dry-run by default.

## Standalone filtering

```bash
npm test 2>&1 | token-saver filter --command "npm test"
pytest -q 2>&1 | token-saver filter --command "pytest -q"
```

The filter removes ANSI noise, compacts valid JSON, abbreviates huge hex blobs, collapses duplicate successful log lines, and applies command-aware reductions. Failure evidence is favored over aggressive compression.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `TOKEN_SAVER_GUARD` | `1` | disable with `0` |
| `TOKEN_SAVER_READ_MAX_LINES` | `220` | maximum guarded source-read window |
| `TOKEN_SAVER_REREAD` | `0` | optional duplicate full-read denial |
| `TOKEN_SAVER_ALLOW` | empty | colon-separated source allowlist globs |
| `TOKEN_SAVER_MIN_LINES` | `40` | minimum Bash stdout lines considered for filtering |
| `TOKEN_SAVER_MAX_LINES` | adaptive | filtered output line target |
| `TOKEN_SAVER_KEEP_TAIL` | `15` | tail retained by generic filtering |
| `TOKEN_SAVER_CACHE_TTL_MIN` | `5` | advisory cache-gap classification only |
| `TOKEN_SAVER_STATE_DIR` | `~/.claude/token-saver` | local state and recoverable output storage |

## Design principles

Token Saver follows six rules:

1. **Select before compressing.** The cheapest irrelevant context is context never loaded.
2. **Structure before bodies.** Outlines locate the small exact ranges worth reading.
3. **Exact bytes for edits.** Source windows are never semantic summaries.
4. **Failures are evidence.** Diagnostics are preserved rather than optimized away.
5. **Compression must be recoverable.** Omitted command output is stored locally.
6. **Measure task outcomes.** Token counts alone are not proof of end-to-end savings.

## Development

```bash
python -m pip install '.[dev]'
python -m pytest -q
```

CI runs the full suite on Python 3.10, 3.12, and 3.13.

See [INTEGRATIONS.md](INTEGRATIONS.md) for agent setup, [CHANGELOG.md](CHANGELOG.md)
for release history, and [VALIDATION.md](VALIDATION.md) for validation limits.

# Token Saver 1.2.0

Token Saver is a local context-optimization layer for AI coding agents. It reduces unnecessary source, tool-output, and always-on context while preserving exact code where the model needs it.

The project is deliberately conservative: **smaller context is useful only when the task still succeeds**. Token Saver does not claim a universal percentage reduction in task cost. It measures input size, preserves diagnostics, and keeps omitted command output recoverable.

## Output Saver: reduce generated tokens too

Token Saver can now control the other side of the bill: model output. The output
layer is deliberately split into **generation-time policy** and **safe
post-generation compaction**.

Generate a compact response policy for an agent:

```bash
token-saver output-policy --mode terse
token-saver output-policy --mode normal --max-tokens 700 --json
```

The policy tells the agent to avoid task restatement, tool narration, repeated
logs/context, unchanged full-file reproduction, verbose test output, and
post-success filler. Default targets are 300 tokens for `terse`, 800 for
`normal`, and 2,000 for `detailed`.

Compact an already-generated response:

```bash
cat response.md | token-saver output-save --mode terse
token-saver output-save response.md --max-tokens 500 --enforce-budget --json
```

Safe compaction removes exact repeated prose/status echoes and trivial filler.
Fenced code and diffs are preserved byte-for-byte. `--enforce-budget` may trim
prose, but **never truncates a fenced code/diff block**; if preserved code alone
cannot fit, the result reports `budget_exceeded: true` instead of corrupting
the answer.

For agent-to-agent state, compact JSON avoids prose and pretty-print overhead:

```bash
cat result.json | token-saver output-save --structured --mode terse
```

The same capabilities are exposed through MCP as `output_policy` and
`compact_output`. This lets an orchestrator inject the response policy before
the model generates tokens, which is the primary savings path; post-processing
cannot refund tokens that were already generated.


## Typo-tolerant retrieval and context browser

Token Saver now has a conservative typo/fuzzy layer designed to complement,
not replace, structural retrieval.

Repository-level typo correction compares query words only against indexed
identifier vocabulary, uses strict similarity and ambiguity margins, and keeps
the original terms. Once a file has already survived retrieval, a slightly
broader fuzzy fallback can rescue a misspelled symbol identifier without
turning fuzzy similarity into a repository-wide ranking signal.

Inspect what the real packer is considering:

```bash
token-saver browse . --query "rendr template"
token-saver browse . --query "refresh sesion token" --show 1
token-saver browse . --query "cookie persistence" --interactive
token-saver browse . --query "redirect request" --json
```

Interactive mode supports `list`, `show N`, and `quit`. The browser reuses
the same file ranker, graph evidence, exact source-window selection, secret
redaction, and source-visible symbol accounting as `pack`; it is not a second
search engine. It also surfaces any high-confidence fuzzy corrections so a
human or agent can see why a typo matched an identifier.

The same inspection surface is available through MCP as `browse_context`.


## Measure cost per successful task

Context reduction is not the same thing as invoice reduction. Token Saver can
compare paired baseline and optimized agent runs directly:

```bash
token-saver cost-report baseline.json token-saver.json
token-saver cost-report baseline.json token-saver.json --json
```

Each run records a `task_id`, success outcome, input/output/cache tokens,
tool/model calls, latency, and optionally `cost_usd`. If the provider bill is
not already available, pass token pricing instead:

```bash
token-saver cost-report baseline.json token-saver.json \
  --input-per-million 10 \
  --output-per-million 30 \
  --cached-input-per-million 2
```

The report computes total cost, success rate, **cost per successful task**,
token/cost/latency reductions, call-count changes, and tasks whose outcome
improved or regressed. By default the two files must contain exactly the same
task IDs so cost comparisons cannot silently use different workloads.


## What is new in 1.2

Retrieval ranking got a full correctness pass, driven by a frozen,
independently-authored external holdout benchmark
([encode/httpx](https://github.com/encode/httpx),
[colinhacks/zod](https://github.com/colinhacks/zod)) rather than this
repository's own self-referential test corpus -- the kind of generalization
check that catches bugs a self-benchmark structurally can't see. Symbol
recall on that frozen suite went from 16.7% to 83.3% this release, with
every fix validated against the self-benchmark first and the frozen suite
checked only once, after the fact, per task -- never as a tuning loop.

Fixed:

- a per-file symbol window preferring a densely-worded helper method over
  the semantically-correct class/function the query was actually about
  (`DigestAuth`-shaped: right file, wrong symbol);
- a TypeScript type alias's inline right-hand side going uncapped into its
  ranking signature (missing the same body/signature truncation every
  other symbol kind gets), letting a type describing a function's return
  shape outscore the function itself;
- the resulting parent-credit fix over-applying to a function containing a
  nested helper function, not just class/method containment;
- `dependency_closure`'s graph-hop seeding missing a relevant-but-low-raw-
  score file's exact semantic reference to a small provider file, fixed
  with a separate, cheap, non-transitive one-hop scan.

Still open and disclosed rather than silently left broken: a terse,
precisely-correct file (e.g. one of bare regex constants) can still lose
the file-ranking competition to a larger file that merely discusses the
same topic in prose. Two fix attempts were tried and reverted after each
broke a different, previously-passing case; see CHANGELOG.md for the full
account of both, including the one that looked clean on the self-benchmark
and only failed on the frozen holdout.

Also merged this cycle: index-backed retrieval performance, stronger JS/TS
module semantics (including NodeNext-style `.js`-specifier resolution to
`.ts` source), adaptive retrieval budgeting, a TypeScript-compiler semantic
overlay, and `token-saver host-check` for validating hook acceptance
against a real, separate Claude Code host process rather than a simulated
payload. See CHANGELOG.md and VALIDATION.md for full detail on all of the
above.

The included deterministic benchmark now measures **92% relevant-file
recall, 96% relevant-symbol recall, and ~95.3% mean estimated context
reduction** at a 6,000-token cap on this repository (88%/92%/93.83% at
1.1). These are retrieval measurements, not an end-to-end claim about
agent success, and move slightly release to release as the tool's own
source -- part of the benchmark corpus -- changes; re-run
`token-saver evaluate` for the exact figure on your checkout.

## What was new in 1.1

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

v1.1 adds:

- SQL/JSON/YAML and `.env.example`-style indexing with dedicated symbol
  extraction -- table names, npm scripts, CI job ids, env vars;
- budgeted evidence allocation: database/config/CI/test evidence that is
  entirely newly-added (so the usual changed-file priority can't reach it)
  gets a small, fair-share-capped guaranteed budget share instead of
  competing purely on relevance score against large new source files;
- a `coverage` field (and a `# coverage: N/M changed files represented`
  footer) distinguishing selected, closure-only, policy-excluded, and
  simply-didn't-fit changed files;
- fixed `pack-diff`/`review` returning an empty pack on large diffs, a
  20-30x impact-analysis performance cliff, and the changed-file boost
  being a no-op for a historical `--base` range -- see CHANGELOG.md for
  each fix.

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

The included deterministic benchmark currently measures **88% relevant-file
recall, 92% relevant-symbol recall, and 93.83% mean estimated context
reduction** at a 6,000-token cap. These are retrieval measurements, not an
end-to-end claim about agent success. Numbers move slightly as the tool's
own source -- part of the benchmark corpus -- changes; re-run
`token-saver evaluate` for the exact figure on your checkout.

## What was new in 1.0

Token Saver compiles both tasks and patches into bounded, explainable context:

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

For paired real-agent outcomes:

```bash
token-saver agent-evaluate benchmarks/agent-runs.example.json
```

The evaluator reports a token-per-success reduction only when the Token Saver
condition preserves baseline success rate.

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

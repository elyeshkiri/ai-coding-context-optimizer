# Token Saver 1.4.0

Token Saver is a local context-optimization layer for AI coding agents. It reduces unnecessary source, tool-output, and always-on context while preserving exact code where the model needs it.

The project is deliberately conservative: **smaller context is useful only when the task still succeeds**. Token Saver does not claim a universal percentage reduction in task cost. It measures input size, preserves diagnostics, and keeps omitted command output recoverable.

## Failure-aware tool output and diagnostic Delta

Bash output now goes through a pluggable processor registry rather than one
monolithic filter. Format-specific processors currently cover pytest, Jest/Vitest,
`git log`, and npm/pnpm/yarn/bun installs, with a conservative generic fallback.
A processor must explicitly opt into failed-command handling; unknown failures
pass through unchanged. After every processor, a shared critical-line recovery
pass restores omitted error/location lines, and a ratio gate rejects marginal or
larger rewrites.

Inspect routing without running a command:

```bash
token-saver output-explain "pytest -q"
token-saver output-explain "npm install" --exit-code 1
```

Replay captured output against explicit preservation and savings contracts:

```bash
token-saver output-replay benchmarks/output-quality.example.json
```

Each case can require exact diagnostic strings, a maximum output-token budget,
and a minimum reduction. A failed contract exits non-zero, so the same fixtures
can guard CI.

Repeated pytest and Ruff diagnostics can optionally use **graph-aware Delta**:

```bash
export TOKEN_SAVER_DELTA=1
```

See [OUTPUT_OPTIMIZATION.md](OUTPUT_OPTIMIZATION.md) for the processor contract,
failure-routing rules, critical-line recovery, replay manifest schema, Delta
state model, and graph-enrichment behavior.

Within one Claude Code session, subsequent runs classify diagnostics as
`NEW`, `CHANGED`, `UNCHANGED`, or `RESOLVED`. New and changed diagnostics
are mapped through Token Saver's repository index to the containing symbol and
nearby dependency/call-graph edges. Only bounded structured diagnostics are
stored in session state; raw command output is not persisted by Delta. Delta
replaces the normal compressed output only when the rendered delta is smaller.

## Install

```bash
pip install claude-token-saver
```

The distribution is named `claude-token-saver` because PyPI rejects
`token-saver` as too similar to an unrelated existing project. The command
and the import are unchanged:

| | Name |
|---|---|
| Install | `claude-token-saver` |
| Command | `token-saver` |
| Import | `token_saver` |

This is an independent project and is not affiliated with or endorsed by
Anthropic.

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

### Explain ranking score decisions

Ranking observability is opt-in so ordinary packing does not pay for trace
collection. Ask for a stage-by-stage breakdown when diagnosing a surprising
candidate:

```bash
token-saver ranking-explain . --query "refresh session token"
token-saver ranking-explain . --query "refresh session token" --max-files 3 --json
```

Each candidate reports its final score plus exact score transitions such as
BM25, path/symbol evidence, structural authority, file-priority adjustments,
changed/working-set/feedback boosts, graph closure, embeddings, and custom
registered rerankers. Legacy `reasons` remain available unchanged.

The same structured payload is exposed through MCP as `explain_ranking`.
Third-party `RankingStage` implementations are traced automatically when an
explanation is requested; plugins do not need their own observability API.

### Diff ranking behavior across commits/configurations

Capture the same frozen task manifest on each revision or configuration:

```bash
token-saver ranking-snapshot benchmarks/context-quality.json \
  --path . --max-files 20 --out baseline-ranking.json

# after checking out or configuring the candidate
token-saver ranking-snapshot benchmarks/context-quality.json \
  --path . --max-files 20 --out candidate-ranking.json

# configuration experiments are captured in snapshot metadata too
token-saver ranking-snapshot benchmarks/context-quality.json \
  --path . --graph-hops 2 --closure-items 30 --out graph-v2-ranking.json
```

Then compare the artifacts:

```bash
token-saver ranking-diff baseline-ranking.json candidate-ranking.json
token-saver ranking-diff baseline-ranking.json candidate-ranking.json --json
```

The diff follows every expected file from the manifest, even when it falls below
the displayed top-N, and reports rank movement, score movement, and the
per-stage contribution changes that caused it. Snapshots with different
ground-truth hashes are rejected instead of producing misleading comparisons.

For CI, fail when an expected file disappears or drops farther than an allowed
amount:

```bash
token-saver ranking-diff baseline-ranking.json candidate-ranking.json \
  --fail-on-regression --allowed-rank-drop 1
```

This workflow intentionally separates snapshot capture from comparison, so the
same diff engine works across Git commits, feature flags, plugin registries,
model/embedding availability, or CI artifacts without managing hidden worktrees.

Pull requests run this comparison automatically against the protected base SHA.
CI checks out the base and candidate separately, uses the **base manifest for
both snapshots**, writes the Markdown comparison to the GitHub Actions job
summary, and uploads `baseline-ranking.json`, `candidate-ranking.json`, and
`ranking-diff.json` as a 14-day artifact.

Rank movement is intentionally informational for now: broken snapshot/diff
execution fails CI, but ranking regressions do not block merges until a
data-backed rank-drop threshold has been calibrated from real PR history.

### Calibrate a blocking policy from PR history

Each PR artifact now carries its pull-request number, workflow run/attempt, base
SHA, and candidate SHA. A separate **Ranking Calibration** workflow runs weekly
and on manual dispatch. It downloads the newest `ranking-regression-<PR>`
artifact per PR, so workflow reruns do not masquerade as independent evidence.

The workflow groups reports by frozen ground-truth hash and evaluates only the
current `benchmarks/context-quality.json` cohort. Old benchmark definitions are
kept separate instead of contaminating the current policy.

You can run the same calibration locally:

```bash
token-saver ranking-calibrate ./ranking-history \
  --ground-truth-sha <CURRENT_HASH> \
  --min-reports 20 \
  --markdown
```

The report includes report/observation counts, expected-file regressions,
disappearances, empirical positive rank-drop percentiles, and scoring-stage
activity. It also states whether the available history factually supports a
zero-rank-drop and/or no-disappearance policy after the configured minimum
sample count.

Calibration is deliberately descriptive: it does **not** call historical
regressions "noise" or automatically choose an allowed rank drop. That decision
remains a separate ratchet once enough representative PR history exists.


## Benchmark Output Saver compaction

Measure the deterministic post-generation layer with a reusable manifest:

```bash
token-saver output-benchmark benchmarks/output-saver.json
```

Each case can provide inline `text` or a response `path`, plus its response
mode, token budget, budget enforcement setting, and strings that must survive
compaction. The report measures original/output tokens, weighted reduction,
code-fence preservation, required-content preservation, and budget overflow.

This benchmark deliberately measures only deterministic **post-generation**
compaction. Generation-time policy savings must be measured from actual model
runs and can be compared with `token-saver cost-report`.


## Run broad end-to-end cost experiments

For publishable cost-per-success evidence, Token Saver can execute frozen paired
coding experiments rather than relying on a handful of manually recorded runs.
The harness uses pinned detached worktrees, randomized baseline/enabled order,
independent verifier commands, repeated trials, real Claude Code transcripts,
and resumable checkpoints.

```bash
# freeze task/design definition before paid runs
token-saver experiment benchmarks/e2e-suite.json --print-task-definition-hash

# inspect the randomized 20-50 task schedule without calling a model
token-saver experiment benchmarks/e2e-suite.json --out benchmark-runs.json --dry-run

# execute, then require the broad-evidence protocol in analysis
token-saver experiment benchmarks/e2e-suite.json --out benchmark-runs.json
token-saver benchmark benchmark-runs.json --rates rates.json --require-publishable
```

The publication gate requires at least **20 distinct tasks** and **3 paired
trials per task**. Cost/success confidence intervals are bootstrapped by task,
so repeated trials of one task do not inflate the effective sample size. See
[BENCHMARKING.md](BENCHMARKING.md) for the frozen-suite protocol and runner
schema.

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

The same paired manifest already used by `agent-evaluate` can be passed
directly as a single argument, so correctness and economics stay attached to
one experiment artifact:

```bash
token-saver agent-evaluate benchmarks/agent-runs.json
token-saver cost-report benchmarks/agent-runs.json
```

Paired manifests use `task` plus
`condition: baseline|token-saver`; `seconds` is accepted as latency and is
normalized to milliseconds in the cost report.


## What is new in 1.3

v1.3 turns the external holdout program into the primary retrieval-quality
signal and adds exact callable-identity evaluation across six languages.

The release includes frozen external holdouts #2 through #11, culminating in
holdout #11: **60 source-grounded tasks across 10 previously-unused
repositories** spanning C#, Java, TypeScript, Rust, Go, and Python. Its first
and only fresh run measured:

| Metric | Fresh holdout #11 |
| --- | ---: |
| File recall | **96.67%** |
| Bare symbol recall | **96.67%** |
| Symbol recall in expected files | **93.33%** |
| Qualified-symbol recall | **91.67%** |
| Exact symbol-identity recall | **88.33%** |
| Mean estimated context reduction | **99.71%** |

Six of the ten fresh repositories were perfect through exact identity. In
particular, .NET Runtime and EF Core both scored 100% through exact identity,
providing independent validation of the new C# 14
`extension(Receiver receiver) { ... }` compatibility extraction beyond the
RestSharp development case that originally exposed the parser gap.

The seven misses from the fresh #11 run were then treated as **burned
development evidence**, not as a new holdout. General fixes were added for
partial TypeScript parser recovery, interface/generic member identity,
same-name top-level TypeScript functions, explicit Go receiver/member
authority, and Java overloads with explicitly excluded parameters. A single
development-only rerun of frozen #11 reached **100% file, bare, scoped,
qualified, and exact identity recall on all 60 tasks**, with the same ~99.71%
mean context reduction. The preserved fresh first-run result above remains the
independent generalization evidence.

The repository's included 25-task self-benchmark is now saturated at **100%
file recall, 100% symbol recall, and 100% scoped symbol recall**, with
**97.90% mean estimated context reduction** at a 6,000-token cap. Because that
self-benchmark is no longer discriminative, external frozen holdouts are the
stronger quality signal. CI currently runs **474 tests** on Python 3.10, 3.12,
and 3.13.

Other 1.3 highlights include:

- exact `path:qualified@line` callable identities and scoped-symbol recall;
- C# 14 extension-block recovery while published tree-sitter-c-sharp 0.23.x
  still lacks native `extension_declaration` support;
- stronger overload-family ranking across Java, C#, and TypeScript;
- lower/camel-case member authority and explicit container/member ranking;
- Rust trait/member and Go receiver-aware identity improvements;
- deterministic `(task_id, trial)` pairing and cluster-bootstrap confidence
  intervals in cost reports;
- hardened repository indexing around malformed, generated, deeply nested, or
  partially parseable source.

See [VALIDATION.md](VALIDATION.md) for the exact methodology, frozen hashes,
first-run/burned distinction, and current CI evidence.

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

At the 1.2.0 release point, the included deterministic benchmark measured
**92% relevant-file recall, 96% relevant-symbol recall, and ~95.3% mean
estimated context reduction** at a 6,000-token cap (88%/92%/93.83% at 1.1).
Those are historical 1.2.0 measurements; the current 1.3.x result is reported
above and in `VALIDATION.md`.

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
pip install 'claude-token-saver[embeddings]'
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

A full `Read` of a large source file is denied before it enters context. So is a lone `cat <large source file>` through Bash, which is the same dump by another route; pipes, redirects, chains and globs are left alone. The denial contains a capped structural outline with line-number gutters so the agent can request an exact range instead.

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
| `TOKEN_SAVER_DELTA` | `0` | opt-in graph-aware pytest/Ruff diagnostic Delta |
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

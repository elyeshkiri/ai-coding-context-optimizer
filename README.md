# Token Saver 1.12.0

Token Saver is a local context-optimization layer for AI coding agents. It reduces unnecessary source, tool-output, and always-on context while preserving exact code where the model needs it.

The project is deliberately conservative: **smaller context is useful only when the task still succeeds**. Token Saver does not claim a universal percentage reduction in task cost. It measures input size, preserves diagnostics, and keeps omitted command output recoverable.

## Install

For Claude Code only, the repository now exposes a marketplace:

```text
/plugin marketplace add elyeshkiri/token-saver
/plugin install token-saver@token-saver-tools
```

Claude shows the command-source bootstrap for approval before running it. The
command-source marketplace path requires Claude Code **2.1.229+**. Older Claude
Code versions can use the pip + setup path below. The generated plugin calls
`python -m token_saver.entry`, so it does not depend on the `token-saver`
console script being on `PATH`.

For Claude + Cursor + Codex, or explicit project-managed installation:

```bash
pip install claude-token-saver
cd /path/to/project
token-saver setup
token-saver doctor
```

`setup` auto-detects Claude Code, Cursor, and Codex, writes only Token
Saver-owned integration entries, creates a project `.token-saver.toml`, and is
safe to rerun after upgrades as a repair/migration step. Configure hosts
explicitly when needed:

```bash
token-saver setup . --host claude --host cursor
token-saver setup . --host all
```

`doctor` consolidates CLI, project-config, host-integration, repository-index,
and available Claude transcript evidence in one health report. Remove only
Token Saver-owned entries with:

```bash
token-saver uninstall . --host all
token-saver uninstall . --host all --remove-config
```

Discover commands without opening the README and enable shell completion:

```bash
token-saver commands
token-saver completion bash
token-saver completion zsh
token-saver completion fish
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

## Documentation

Start with the task-oriented docs instead of searching this README:

- [5-minute quickstart](docs/QUICKSTART.md)
- [Worked end-to-end example](docs/WORKED_EXAMPLE.md)
- [CLI reference](docs/CLI_REFERENCE.md)
- [Machine-readable CLI contracts](docs/JSON_OUTPUTS.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Claude Code / Cursor / Codex integrations](INTEGRATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Upgrading and migration](docs/UPGRADING.md)
- [Architecture](ARCHITECTURE.md)
- [Benchmarking methodology](BENCHMARKING.md)
- [Validation evidence](VALIDATION.md)
- [Security and privacy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

The complete documentation map is [docs/README.md](docs/README.md).

## Cost intelligence and efficiency advisor

Turn local Token Saver evidence into a practical optimization report:

```bash
token-saver cost-advisor .
token-saver cost-advisor . --project-only --json
token-saver pricing --model claude-sonnet-5
token-saver model-route "Debug this failing authentication handler" --json
token-saver cost-advisor . \
  --rates benchmarks/claude-sonnet-5-rates-2026-09-19.json
```

The advisor scores only categories with enough evidence and reports score
coverage separately. It combines measured always-on context, Claude transcript
usage/cache counters, output-budget fit, continuity/waste signals, and observed
before/after tool-context reductions.

Automatic model-routing intelligence is available through the CLI, MCP
`route_task`, and the opt-in Claude prompt hook. Routing first applies a
deterministic task/complexity/risk capability floor, then selects the cheapest
eligible profiled model from the fresh built-in pricing registry. Claude's hook
can advise and measure the decision; model-selectable orchestrators can execute
it directly through MCP. The built-in capability profiles are conservative
product policy, not a benchmark ranking of model quality.

Routing can become more aggressive only through a generated quality-gated
calibration artifact. Calibrate a cheaper arm against the current static-policy
model on frozen paired tasks, keep all non-model arm settings identical, verify
task success independently, blind-grade the final responses, then run:

```bash
token-saver model-route-calibrate routing-runs.json
```

The default gate requires at least 10 pairs across 5 tasks, at least 80%
baseline success, zero lost baseline successes, blind correctness/safety/
weighted-quality parity within 0.10 points, and transcript-confirmed actual
models. Accepted evidence relaxes only the exact task/complexity/risk bucket.

Pricing is deliberately explicit: dollar usage is calculated only from an
explicit exact-model rates source. Pass `--rates builtin` to use Token Saver's
source-attributed, freshness-gated packaged registry, or supply a frozen JSON
rate file for reproducible historical evidence. Mixed-model turns, missing model prices,
or unknown cache-write TTLs stay visibly unpriced instead of being allocated by
assumption. Estimated tool-context savings may be shown under a clearly labeled
fresh-input-once scenario, but are **not** presented as measured API savings or
cost-per-success evidence.

## Safe oversized-prompt ingress

Claude Code's `UserPromptSubmit` hook can block a prompt or add context, but
cannot replace the submitted text. Token Saver therefore does **not** claim to
rewrite a huge prompt before the model.

Instead, an explicit opt-in can stage very large prompts losslessly:

```toml
[ingress]
enabled = true
threshold_tokens = 12000
packet_tokens = 1600
```

When the threshold fires, Token Saver stores the exact prompt locally with a
SHA-256 integrity digest and returns a blocking stage id before Claude processes
the prompt. Resume with the generated plugin skill:

```text
/token-saver:ingress STAGE_ID
```

or manually:

```bash
token-saver ingress-show STAGE_ID --path .
token-saver ingress-read STAGE_ID --path . --start-line 80 --end-line 140
```

The packet contains exact bounded head/tail excerpts plus explicit omitted line
ranges. **There is no silent first-N-words truncation fallback.**

## Smart Tool Proxy for large Reads

Claude Code can opt in to routing large unbounded source Reads through Token
Saver before the result reaches Claude:

```toml
[tool_proxy]
enabled = true
provider = "ollama"
model = "qwen2.5-coder:7b"
endpoint = "http://127.0.0.1:11434"
min_tokens = 2500
target_tokens = 1800
```

The free/local model is a **range selector, not a source of truth**. Token Saver
builds bounded structural/exact candidate evidence, asks the selector which
ranges matter for the current task, validates those ranges, then rehydrates the
delivered excerpts from the real file bytes. Selector prose is explicitly
marked non-authoritative. If Ollama is unavailable, times out, or returns invalid
JSON, Token Saver falls back to deterministic structural/lexical range
selection.

```text
Claude Read(large source)
        ↓
PreToolUse delegates eligible read
        ↓
local Ollama selector (optional)
        ↓
validated line ranges
        ↓
exact excerpts from original source
        ↓
PostToolUse updatedToolOutput
        ↓
Claude receives bounded evidence
```

Bounded Reads remain untouched and are the exact-byte recovery path for edits.
The feature is disabled by default; no source is sent to a model unless it is
explicitly enabled. See [Configuration](docs/CONFIGURATION.md) and
[Security & privacy](SECURITY.md).

## Smart Tool Proxy for large Reads

Claude Code can opt in to routing large unbounded source Reads through Token Saver before the result reaches Claude:

```toml
[tool_proxy]
enabled = true
provider = "ollama"
model = "qwen2.5-coder:7b"
endpoint = "http://127.0.0.1:11434"
min_tokens = 2500
target_tokens = 1800
```

The free/local model is a **range selector, not a source of truth**. Token Saver builds bounded structural/exact candidate evidence, asks the selector which ranges matter for the current task, validates those ranges, then rehydrates the delivered excerpts from the real file bytes. No selector-generated prose is forwarded to Claude. If Ollama is unavailable, times out, or returns invalid JSON, Token Saver falls back to deterministic structural/lexical range selection.

```text
Claude Read(large source)
        ↓
PreToolUse delegates eligible read
        ↓
local Ollama selector (optional)
        ↓
validated line ranges
        ↓
exact excerpts from original source
        ↓
PostToolUse updatedToolOutput
        ↓
Claude receives bounded evidence
```

Bounded Reads remain untouched and are the exact-byte recovery path for edits. The feature is disabled by default; no source is sent to a model unless it is explicitly enabled. See [Configuration](docs/CONFIGURATION.md) and [Security & privacy](SECURITY.md).
## Hybrid semantic retrieval

Token Saver 1.10 adds opt-in **chunk-level semantic discovery** without turning
semantic summaries into edit context. Enable it with either spelling:

```bash
token-saver pack . --query "where do stale sessions get rejected?" --semantic
token-saver pack . --query "where do stale sessions get rejected?" --embeddings
```

The flow is:

```text
versioned structural index
        ↓
symbol-aware chunks + overlapping fallback windows
        ↓
persistent local vectors
        ↓
exact cosine or optional HNSW
        ↓
multi-hit semantic file ranking
        ↓
bounded semantic → dependency-provider expansion
        ↓
existing exact-source symbol/window selector
        ↓
live exact source bytes
```

Install the one-step semantic extra, then explicitly download the local model
once:

```bash
pip install 'claude-token-saver[semantic]'
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
token-saver semantic-index .
token-saver semantic-status .
```

At Token Saver runtime the model loader uses `local_files_only=True`; semantic
retrieval does not silently fetch a model from the network. For reproducible
evaluation or controlled deployments, set
`TOKEN_SAVER_SEMANTIC_MODEL_REVISION=<immutable-model-revision>`. The revision
participates in vector-store and cached-query identity, so different model
weights cannot silently share semantic state. The SQLite index
stores vectors plus repository-relative path/line/symbol coordinates, **not
source text**. If `hnswlib` is unavailable the same vectors use exact cosine
scan instead of changing retrieval semantics.

Semantic evidence is deliberately bounded below exact structural authority.
The semantic stage aggregates up to three non-redundant chunks per file and its
boost is independent of lexical rank, so a weak-lexical candidate is not
penalized twice. Top semantic witnesses can also contribute a small one-hop
dependency/provider boost, allowing a descriptive caller/test to surface a
terse implementation. Exact requested API identity still carries much more
weight than any semantic contribution.

## Persistent retrieval cache and optional Rust fastpath

Application-level context building now caches completed packs across processes
when the repository content fingerprint and retrieval configuration are
identical. Source digests, index version, changed-file state, ranking feedback,
working-set state, and budget/query settings are part of cache identity.
Embeddings/custom ranking plugins bypass caching until their external state can
be fingerprinted safely.

```toml
[retrieval]
cache = true
cache_max_entries = 64
```

Token Saver also has a separately buildable optional PyO3 accelerator under
`rust/token_saver_fast`. Python remains the reference implementation and
automatic fallback. Inspect the active backend with:

```bash
token-saver fastpath-status
```

CI builds the Rust wheel and reruns pack/retrieval/context-quality checks with
the native backend required before accepting fastpath changes.

The normal `claude-token-saver` wheel remains pure Python. To try the optional
native accelerator from a source checkout:

```bash
python -m pip install maturin
python -m pip install ./rust/token_saver_fast
token-saver fastpath-status
```

If the extension is absent or fails to import, Token Saver automatically uses
the Python reference implementation.

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

## Frozen session-efficiency holdout

Version 1.8 adds a dedicated causal benchmark for the 1.7 session layer. It
reuses the already-frozen **24 SWE-bench Verified tasks × 3 trials** but compares
two condition profiles of the **same current Token Saver binary**:

```text
v1.6 session-behavior baseline
  Token Saver installed
  continuity=off
  cross-turn dedup=off
  waste detection=off

v1.7 session-efficiency treatment
  Token Saver installed
  continuity=on
  cross-turn dedup=on
  waste detection=on
```

This isolates the session-efficiency bundle from unrelated 1.7 changes such as
new output processors. It is a behavioral baseline, **not** execution of the
historical 1.6 package.

Each arm is deliberately split into two fresh Claude sessions: an
investigation-only phase, then a real `SessionStart:resume` boundary, then a
fresh implementation phase. The control gets no continuity context; the
treatment can receive the structured checkpoint. The benchmark independently
derives tool calls, repeated commands, identical-failure retries, duplicate
Reads, and token usage from raw transcripts. Token Saver's own efficiency events
are used only to prove which mechanisms activated.

Run/resume locally:

```bash
token-saver session-holdout \
  benchmarks/session-efficiency-swebench-24.frozen.json \
  --out session-holdout-runs.json \
  --require-publishable
```

Evaluate already merged/blind-graded evidence without rerunning agents:

```bash
token-saver session-holdout-evaluate session-holdout-runs.json \
  --rates benchmarks/claude-sonnet-5-rates-2026-09-19.json \
  --json --require-publishable
```

The frozen publication gate requires ≥20 tasks, ≥3 trials/task, isolated arm
profiles, independent task success, blind response-quality parity, no manual
intervention, complete cache-TTL-aware cost evidence, zero session-efficiency
events in the control, one forced continuity restore per treatment run, and
observed dedup + continuity + waste signals somewhere in the treatment. A
cost-per-success claim additionally requires a positive point estimate and a
task-cluster 95% confidence interval whose lower bound is above zero.

The checked-in paid workflow represents **144 arm-runs / 288 Claude task
phases**, plus blind grading. It is manual/explicitly confirmed. No session-
efficiency savings percentage is claimed until that workflow is actually run
and passes its publication gate.

## Session efficiency: preserve work, not conversation

Token Saver 1.7 adds a host-neutral session-efficiency layer around the existing
repository/retrieval and output pipelines.

With Claude Code project hooks installed it now:

- restores a compact **structured continuity checkpoint** after resume/compaction;
- collapses exact repeated Bash output for the same command and blocks unchanged
  repeated full-file Reads;
- detects bounded retry loops, repeated commands, and long no-edit tool cascades;
- tracks working files plus recent test/lint/typecheck/build outcomes without
  storing raw prompt or assistant text;
- records accepted tool-context reductions in a private local event ledger.

Inspect the current working checkpoint:

```bash
token-saver continuity .
token-saver continuity . --json
```

Inspect local efficiency telemetry in the terminal/JSON or generate a
dependency-free HTML dashboard:

```bash
token-saver dashboard . --days 7
token-saver dashboard . --json
token-saver dashboard . --html .token-saver-dashboard.html
```

The dashboard deliberately separates exact available Claude usage counters from
**estimated before/after tool-context tokens saved**. It does not turn those
operational estimates into a cost-per-success or quality claim; the frozen
`evidence-run` pipeline remains the publication-grade surface.

Command compression also expands beyond pytest/Jest/git-log/package installs to
git status, grep/ripgrep/find, Ruff/ESLint/Pylint/Clippy, tsc/mypy/pyright,
Go/Cargo tests, common build systems, Python package installs, and
Docker/Kubernetes logs. Unknown failures still pass through conservatively and
critical-diagnostic recovery remains registry-wide.

## Durable project knowledge: reuse conclusions, not just context

Token Saver can now keep explicit, evidence-backed findings across sessions without
turning session continuity into a transcript memory system. A finding must include
a claim, concrete evidence, an applicability rule, and at least one current
repository file anchor:

```bash
token-saver remember . \
  --claim "Session refresh is implemented in the auth service" \
  --anchor src/auth.py::refresh_session \
  --evidence "refresh_session delegates the rotation path" \
  --applicability "Use when changing login or refresh behavior"

token-saver recall . --query "debug session refresh"
token-saver knowledge-status .
```

Each anchor stores the source-file digest that existed when the finding was
recorded. If that file changes or disappears, the finding becomes `stale` and
ordinary recall excludes it. New findings may explicitly supersede older ones,
and exact claim/anchor duplicates update one record instead of multiplying
context. Storage is local, private, project-scoped, bounded, and contains only
the finding fields the caller explicitly submits.

This first layer is deliberately conservative: findings are **not** automatically
generated from model conversation and are **not** silently injected into every
context pack. CLI/MCP callers explicitly write and recall them, which keeps the
existing retrieval holdouts unchanged while creating a measurable path to future
cross-session read/reasoning avoidance.

The original surface remains available through MCP as `remember_finding`,
`recall_findings`, and `knowledge_status`.

The richer project-memory layer builds on the same evidence store rather than a
second database. Memories can be typed as `decision`, `bugfix`,
`convention`, `guardrail`, `architecture`, `fact`, or `finding`, with
tags, importance, related-memory ids, bounded reuse counters, and gentle
time-decay in ranking. Source digests still win over memory: changed or missing
anchors make a record stale regardless of its importance or reuse.

Agents use progressive disclosure rather than loading full memory records into
every turn:

```text
memory_index(query)     # compact ids / claims / types / scores
        ↓
memory_search(query)    # bounded applicability/evidence snippets
        ↓
memory_get(ids)         # full records only after relevance is confirmed
```

`remember_memory` performs bounded near-duplicate detection within the same
memory type and source anchors; a close replacement supersedes the older active
record instead of leaving two competing memories. Token Saver still does not
auto-harvest raw conversation text or silently inject project memory into normal
context packs.

### Adaptive MCP tool disclosure

Token Saver can advertise a smaller MCP schema instead of paying for every tool
definition on every request:

```bash
TOKEN_SAVER_MCP_PROFILE=minimal token-saver serve .
TOKEN_SAVER_MCP_PROFILE=context token-saver serve .
TOKEN_SAVER_MCP_PROFILE=memory token-saver serve .
TOKEN_SAVER_MCP_PROFILE=adaptive token-saver serve .
TOKEN_SAVER_MCP_PROFILE=full token-saver serve .
```

`full` remains the default and explicit compatibility fallback. `adaptive`
starts with six core tools, including `discover_tools`. The agent supplies the
current task description; Token Saver deterministically maps it to bounded
memory, retrieval, review, output, and routing groups, returns the exact selected
schemas, expands the live `tools/list` surface, and advertises MCP
`listChanged=true`.

Project configuration can opt in without changing host MCP files:

```toml
[mcp]
profile = "adaptive"
adaptive_max_tools = 12
```

The selector uses task vocabulary only, makes no model call, and defaults to
repository-retrieval specialists when the task is ambiguous. Unknown profile
names fail closed instead of silently selecting another surface.

## Knowledge-assisted read avoidance and cache economics

The durable finding store can now participate in the source-read guard, but only
behind an explicit opt-in:

```bash
TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE=1 claude
TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE=1 \
TOKEN_SAVER_CACHE_ECONOMICS=1 claude
```

For an unbounded source `Read`, Token Saver checks for `verified`, active
findings anchored to that exact file. A changed/missing anchor, a probable or
speculative finding, an allowlisted/non-source file, or a bounded range never
qualifies. The replacement must be materially smaller than the file and tells
the agent to request an exact `offset+limit` range whenever implementation
bytes are needed.

The optional cache-economics gate evaluates projected relative input cost rather
than assuming that fewer raw tokens are always cheaper. It models an already
cached prefix separately from the new frontier and charges prefix recreation
when a proposed transformation invalidates cached history:

```bash
token-saver cache-economics \
  --original-frontier-tokens 4000 \
  --replacement-frontier-tokens 800 \
  --cached-prefix-tokens 12000 \
  --invalidates-cached-prefix \
  --expected-reuses 2
```

The default 1.25 cache-write and 0.10 cache-read factors are planning defaults,
not universal provider pricing. Override them for the active provider/model.

### Frozen knowledge-efficiency holdout

The feature is **not enabled by default and no end-to-end savings percentage is
claimed yet**. A separate frozen causal experiment reuses the 24 SWE-bench
Verified tasks at three trials per task. Both arms run the same current Token
Saver binary, disable continuity/dedup/waste features, perform the same
investigation phase, and explicitly persist verified findings. A fresh
implementation session then compares memory-control against knowledge-assisted
read avoidance plus the cache-economics gate.

```bash
token-saver knowledge-holdout \
  benchmarks/knowledge-efficiency-swebench-24.frozen.json \
  --out knowledge-holdout-runs.json \
  --require-publishable
```

Publication requires independent task success, blind response-quality parity,
complete cache-TTL-aware pricing, verified knowledge seeding in every arm-run,
zero control read-avoidance activation, observed treatment activation, and a
strictly positive task-cluster 95% confidence interval for cost-per-success
reduction.

## Output Saver: reduce generated tokens too

Token Saver can now control the other side of the bill: model output. The output
layer is deliberately split into **generation-time policy** and **safe
post-generation compaction**.

With Claude Code hooks installed, Token Saver now applies this policy
automatically at `UserPromptSubmit`. It deterministically classifies strong
coding, debugging, review, planning, and explanation prompts, while ambiguous
follow-ups inherit the active task. The full policy is injected only when the
task or verbosity mode changes, on the first task in a session, or after a
clear/compact reset, avoiding repetitive policy-token overhead.

Manual policy generation remains available for orchestrators and hosts without
a prompt-hook surface:

```bash
token-saver output-policy --mode terse --task coding
token-saver output-policy --mode normal --task debugging --max-tokens 700 --json
```

The policy tells the agent to lead with the useful result, avoid conversational
preambles, task restatement, tool narration, repeated logs/context, tangents,
unchanged full-file reproduction, verbose test output, recaps, and closing
filler. `--task` adapts both wording and default budgets for coding, debugging,
review, explanation, and planning while preserving the historical
300/800/2,000-token defaults when no task is selected.

Debugging policy explicitly separates observations from hypotheses so brevity
does not pressure the model into inventing a root cause. Explicit user output
contracts, required code/diffs, diagnostics, safety information, and material
caveats always override the token target. Explicit requests such as "briefly"
or "in detail" also override the configured automatic verbosity for that task.
Automatic classification stores only resolved policy metadata (task/mode/budget),
not the user's prompt text.

Automatic budgets are adaptive by default. Small/simple tasks can receive less
than the static task budget, while multi-part, repository-wide, code-heavy, or
diagnostic-heavy prompts receive more room within hard mode-specific bounds.
Ambiguous follow-ups keep the active budget unchanged.

Token Saver can also learn safer task/mode bases from real paired experiments:

```bash
token-saver output-calibrate benchmarks/agent-runs.json \
  --out .token-saver.output-calibration.json
```

Calibration accepts only blinded paired evidence, ignores failed/blocked or
quality-regressing Token Saver runs, and requires at least three valid samples from three distinct task IDs
for a task/mode recommendation. The automatic hook consumes that artifact on
future tasks; absent or invalid calibration falls back to built-in defaults.

Claude Code can also record real turn-level usage automatically:

```bash
token-saver output-telemetry .
token-saver output-telemetry . --json
```

The prompt hook checkpoints the transcript byte offset and active policy. At
`Stop` or `StopFailure`, Token Saver reads only transcript bytes appended for
that turn and records input/cache/output token counters, model calls, selected
budget, task/mode, and adaptive/calibration metadata. It does **not** copy prompt
text, assistant text, tool payloads, or transcript content. Telemetry reports
budget-utilization patterns but deliberately does not treat a finished model
turn as verified task success or response quality.

For a complete frozen evaluation, one resumable command now runs the full
evidence chain:

```bash
token-saver evidence-run benchmarks/e2e-swebench-24.frozen.json \
  --out benchmark-runs.json \
  --require-publishable
```

It performs randomized baseline/Token Saver trials, independent hidden
verification, deterministic blind A/B grading, cache-TTL-aware cost-per-success
analysis, and quality-gated adaptive-budget calibration. The shipped frozen
suite contains **24 SWE-bench Verified tasks × 3 paired trials** (144 agent
runs). The GitHub workflow remains explicitly paid/manual and must be executed
before any new savings percentage is claimed.

For paired experiments with independent verification and blind response grades,
join all four evidence layers:

```bash
token-saver output-effectiveness benchmark-runs.json \
  --fresh-input-per-million <rate> \
  --cache-creation-5m-per-million <rate> \
  --cache-creation-1h-per-million <rate> \
  --cache-creation-unknown-per-million <rate> \
  --cache-read-per-million <rate> \
  --output-per-million <rate> \
  --require-publishable
```

The report measures **cost per successful task**, checks blind quality parity,
verifies policy telemetry against the copied transcript, clusters confidence
intervals by task, and identifies task/mode/budget cohorts that have enough
quality-preserving cross-task evidence to be candidates for calibration.

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


## Release history

Release-specific changes live in [CHANGELOG.md](CHANGELOG.md). Validation
results and evidence limitations live in [VALIDATION.md](VALIDATION.md), so this
README stays focused on current usage rather than duplicating historical release
notes.

## Automatic protections

The recommended Claude Code lifecycle is:

```bash
token-saver setup /path/to/project --host claude
token-saver doctor /path/to/project
```

This configures both project hooks and MCP. The lower-level `token-saver
install` command remains available for compatibility and specialized
Claude-only/user-wide hook installation; new projects should normally use
`setup`.

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

`token-saver setup` creates `.token-saver.toml` in the project. Hook and
guard settings can be committed with the repository instead of being repeated
as shell environment variables:

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
```

Existing `TOKEN_SAVER_*` environment variables remain supported and take
precedence over project configuration, which keeps CI/temporary overrides
simple.

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
| `TOKEN_SAVER_INGRESS_OPTIMIZER` | `0` | opt-in lossless oversized-prompt staging before Claude processing |
| `TOKEN_SAVER_INGRESS_THRESHOLD_TOKENS` | `12000` | estimated prompt threshold for ingress staging |
| `TOKEN_SAVER_INGRESS_PACKET_TOKENS` | `1600` | bounded staged packet target |
| `TOKEN_SAVER_RETRIEVAL_CACHE` | `1` | persistent content-fingerprinted completed-pack cache |
| `TOKEN_SAVER_RETRIEVAL_CACHE_MAX_ENTRIES` | `64` | bounded cache entries per project |
| `TOKEN_SAVER_RUST_FASTPATH` | `1` | use optional native extension when installed; `0` forces Python |
| `TOKEN_SAVER_KNOWLEDGE_READ_AVOIDANCE` | `0` | opt-in verified-knowledge replacement for redundant full-file Reads |
| `TOKEN_SAVER_CACHE_ECONOMICS` | `0` | require cache-aware projected-cost approval for knowledge read avoidance |
| `TOKEN_SAVER_CACHE_EXPECTED_REUSES` | `2` | expected future cache reads in the planning model |
| `TOKEN_SAVER_CACHE_WRITE_FACTOR` | `1.25` | relative cache-write input factor; provider/model override recommended |
| `TOKEN_SAVER_CACHE_READ_FACTOR` | `0.10` | relative cache-read input factor; provider/model override recommended |
| `TOKEN_SAVER_CACHE_MIN_RELATIVE_SAVINGS` | `0.05` | minimum projected relative savings for the runtime cache gate |
| `TOKEN_SAVER_CACHE_TTL_MIN` | `5` | advisory cache-gap classification only |
| `TOKEN_SAVER_SEMANTIC_MODEL_REVISION` | unset | optional immutable SentenceTransformer revision; partitions semantic vector/query caches |
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

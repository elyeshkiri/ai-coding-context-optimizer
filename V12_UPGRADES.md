# Indexed and semantic retrieval upgrades

This branch turns Token Saver's task packer into an index-backed context compiler while keeping v1.1 behavior available in `token_saver.legacy_pack` for regression comparison.

## 1. Persistent index-backed retrieval

Repository indexing now persists each file's structural outline and weighted lexical term frequencies alongside symbols, imports, calls and exact symbol ranges. Ranking operates on that persisted metadata; source files are opened only after they win a place in the final evidence set.

```bash
token-saver pack . -q "fix session refresh" --max-tokens 6000
```

The generated header reports `mode: indexed`. A content digest still invalidates only edited files, so warm queries reuse all unchanged retrieval metadata.

## 2. Adaptive context budgeting

Adaptive mode broadens dependency search when lexical ranking is ambiguous and stays narrow when one candidate clearly dominates. It also prevents one large file from exhausting an uncertain pack.

```bash
token-saver pack . -q "fix checkout race" --adaptive-budget --max-tokens 6000
```

The planner remains deterministic; the hard token cap is still enforced by the packer.

## 3. TypeScript semantic resolution

Token Saver can optionally use the repository's already-installed TypeScript compiler to resolve imports, re-exports, call targets and type references to concrete source files. It never installs TypeScript or accesses the network.

```bash
token-saver pack . -q "change checkout policy" --typescript-semantic
```

Use `--strict-semantic` to fail instead of falling back when Node, local TypeScript, or `tsconfig.json` is unavailable. For persistent opt-in, set:

```bash
export TOKEN_SAVER_TS_SEMANTIC=1
```

Compiler-resolved `semantic` / `semantic-reverse` graph edges receive higher closure confidence than heuristic name matching.

## 4. Provider-aware token accounting

Offline estimates remain the default for fast hard-budget planning. Exact/provider-specific raw-text counting is available through the `estimate` command:

```bash
# Anthropic Messages count_tokens API
pip install 'token-saver[anthropic]'
token-saver estimate -f CONTEXT.md --exact --provider anthropic --model claude-sonnet-4-5

# OpenAI tokenizer (local tiktoken; raw text only)
pip install 'token-saver[openai]'
token-saver estimate -f CONTEXT.md --exact --provider openai --model gpt-5.6

# Gemini count_tokens API
pip install 'token-saver[google]'
token-saver estimate -f CONTEXT.md --exact --provider google --model gemini-2.5-pro
```

Provider counters measure the supplied text. They do not claim to reproduce request-envelope/tool-schema overhead; actual billing comparisons should use provider-reported usage from the real agent run.

## 5. Frozen unseen-repository evaluation

The built-in self-benchmark remains useful for regression testing, but publishable claims should be replicated on repositories/tasks the implementation did not tune against. The new harness supports multiple repositories and freezes the independently written ground truth with SHA-256.

Start from `benchmarks/unseen-suite.example.json`, write the expected files/symbols before running Token Saver, then calculate the freeze hash:

```bash
token-saver unseen-evaluate benchmarks/my-unseen-suite.json --print-ground-truth-hash
```

Put that value in `ground_truth_sha256`, commit the manifest, then run:

```bash
token-saver unseen-evaluate benchmarks/my-unseen-suite.json
```

If query/expected evidence/task metadata changes after freezing, evaluation stops instead of silently moving the target. `--allow-unfrozen` is available only for exploratory work.

## 6. Host integration validation

`host-check` verifies installation separately from live-host acceptance:

```bash
# settings + local hook replacement/recovery round trip
token-saver host-check . --require-ready
```

It checks configured Token Saver hooks, probes the host executable version, runs a synthetic 500-line Bash result through the real hook, and retrieves an omitted middle line from the saved original output.

A local round trip does **not** prove the host actually feeds `updatedToolOutput` to the model. Supply a captured host debug transcript for that final gate:

```bash
token-saver host-check . \
  --live-evidence /path/to/claude-debug.log \
  --require-live
```

The command reports `live_verified=true` only when the supplied evidence contains both the host replacement field and Token Saver's filtered-output recovery marker.

## Compatibility

The public `token_saver.pack` API keeps the v1.1 argument defaults. New behavior that can change retrieval breadth—adaptive budgeting and TypeScript semantic resolution—is opt-in. Index-backed ranking itself is now the default and preserves the legacy exact-source-window format and hard token cap.

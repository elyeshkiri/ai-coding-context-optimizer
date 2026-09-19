# Architecture

Token Saver is organized around **small host-independent cores** and thin
integration adapters. The main rule is that adding a command, processor, or host
adapter should not require editing unrelated orchestration logic.

## Dependency direction

```text
CLI entry
  -> CommandRegistry
      -> command handlers
          -> application modules

Claude hook / replay / CLI
  -> OutputPipeline
      -> ProcessorRegistry
          -> OutputProcessor contracts
              -> built-in or custom processors
      -> preservation/text policy

CLI / MCP / future agent hosts
  -> RepositoryContextService
      -> repository index + ranking + graph + packing services
```

The dependency arrows point inward toward contracts and pure application logic.
Host-specific JSON, environment variables, persistence, and subprocess behavior
stay at the edges.

## Command boundary

`token_saver.entry` no longer owns a branch for every top-level command. New
commands are composed in `token_saver.command_registry` as `CommandSpec` values.
`CommandRegistry` is independently testable and preserves fallback to the legacy
CLI for existing commands.

Command implementations are grouped vertically under
`token_saver.command_handlers`:

- `context.py` — repository browsing, impact, and feedback;
- `evaluation.py` — context and agent evaluation;
- `experiment.py` — paired experiments and cost-per-success reporting;
- `host.py` — host validation and MCP serving;
- `output.py` — output policy, compaction, replay, explain, and benchmarks;
- `patch.py` — diff-context packing and patch review.

The registry imports these handlers directly. `token_saver.commands` is retained
only as a compatibility facade for older imports and contains no command
implementation. This keeps command growth local to one user-facing capability
instead of rebuilding a central CLI monolith.

## Repository application boundary

`RepositoryContextService` is the shared application layer for repository-aware
operations. Host-facing code should use it instead of composing
`RepositoryIndex`, context packing, browsing, impact analysis, semantic
enrichment, and ranking feedback independently.

The service owns one repository scope and one reusable index lifecycle. It
provides `build_context`, `browse`, `find_symbols`, `impact`,
`feedback`, `enrich_typescript`, `get`, `refresh`, and `status`.

The main pack CLI, context CLI commands, and repository-oriented MCP tools now
consume this same boundary. `mcp_server.IndexService` remains as a compatibility
subclass so existing imports and MCP index-status behavior stay stable.

This keeps retrieval policy single-sourced while leaving low-level modules such
as `pack.py`, `repo_index.py`, `context_browser.py`, and `impact.py`
independently testable.

## Context-packing pipeline boundary

`token_saver.pack` is now the compatibility facade and final bounded-assembly
stage. Retrieval algorithms are split under `token_saver.packing`:

- `contracts.py` — `RankedFile` and `ContextPack` data contracts;
- `query_analysis.py` — query normalization, structural request hints,
  signature/overload intent, and conservative repository typo expansion;
- `file_scoring.py` — deterministic BM25, path/symbol/structural authority,
  changed/working-set/feedback boosts, candidate filtering, and final sort key;
- `graph_rerank.py` — dependency/semantic-ref closure boosts and optional
  local embedding reranking;
- `ranking.py` — compatibility facade plus the `rank_files` stage orchestrator;
- `symbol_scoring.py` — within-file lexical/structural scoring, overload
  resolution, fuzzy/call-graph evidence, and parent/container credit;
- `symbol_windows.py` — selected-symbol source windows, evidence labels,
  lexical navigation windows, and file-section rendering;
- `symbols.py` — compatibility facade for the pre-split private import surface;
- `render.py` — section fingerprints, visible-symbol accounting, hard-budget
  fitting, and static retrieval-plan construction.

`pack.py` keeps `build_context_pack`, the historical `rank_files` entry point,
and private compatibility aliases used by existing tests/callers. Its
`rank_files` wrapper deliberately resolves changed files through the facade
before entering the extracted stage, preserving the established monkeypatch
seam while leaving the ranking implementation host-independent.

The extraction is behavior-preserving: ranking policy and weights remain in the
same order, and the frozen holdout remains the regression oracle for any future
changes to these stages.

### File ranking stages

File ranking now has a one-way dependency chain:

```text
query_analysis
      ↓
file_scoring
      ↓
graph_rerank
      ↓
ranking.py orchestration
```

`query_analysis.py` has no dependency on scored files or graph traversal.
`file_scoring.py` owns deterministic lexical/structural policy and does not
import closure or embedding implementations. `graph_rerank.py` can adjust an
already-scored candidate set but does not redefine BM25 or structural boosts.
`ranking.py` preserves the historical private helper surface while composing
those stages in the existing order.

`symbol_scoring.py` consumes `query_analysis.py` directly rather than routing
through the ranking compatibility facade. This keeps shared overload/query
interpretation reusable without coupling within-file scoring to repository-level
ranking orchestration.

### Symbol scoring vs rendering

Within-file relevance and source rendering are separate policies.
`symbol_scoring.py` has no repository-index or redaction dependency and does not
format source windows. `symbol_windows.py` consumes the scoring stage to select
symbols, then owns only source-range selection, evidence labels, and section
formatting. `pack.py` imports both implementation stages directly, so the
`symbols.py` compatibility facade is not on the production execution path.

This boundary is intentional: scoring weights and overload policy can be
benchmarked independently from changes to context-line radius, large-container
windowing, source formatting, or redaction.


## Output boundary

The pre-1.4 `token_saver.output_processors` module remains as a compatibility
facade. New code should use the `token_saver.output` package:

- `contracts.py` — processor/result/policy contracts;
- `registry.py` — ordering and failure-aware processor selection;
- `processors.py` — format-specific transformations only;
- `text.py` — shared normalization and critical-diagnostic preservation;
- `pipeline.py` — orchestration and acceptance policy.

This prevents format-specific processors from owning routing or global safety
policy, and lets integrations inject a processor registry without modifying the
pipeline.


## Hook boundary

`token_saver.hook` is now the Claude-specific composition root only. It parses
JSON/stdin, translates environment variables into `HookConfig`, and wires
concrete services. Event routing and replacement policy live in the host-neutral
`HookRuntime`.

`HookRuntime` receives an explicit `HookServices` bundle containing the
`OutputPipeline` contract, Delta application, output persistence, guard,
session/read-state operations, digesting, policy nudges, and token estimation.
This makes host behavior testable without filesystem-backed session state or a
Claude process, and lets another host reuse the same runtime policy with a
different adapter.

## MCP server boundary

`token_saver.serve` is now a compatibility facade and composition root. The
server implementation is split under `token_saver.mcp_server`:

- `contracts.py` — tool/context contracts with no JSON-RPC or stdio knowledge;
- `services.py` — repository-index lifecycle service;
- `tools.py` — tool schemas, application handlers, and `McpToolRegistry`;
- `protocol.py` — JSON-RPC method routing and MCP result/error translation;
- `transport.py` — newline-delimited stdio only.

Tool handlers return plain application values and depend on an explicit
`McpToolContext`. The protocol runtime receives an injectable registry and
index service, and the transport receives an `McpProtocol` instance. This lets
other hosts or transports reuse the exact same tools without importing stdio
behavior or duplicating repository logic.

## Architectural invariants

1. **Fail open:** unknown failed output is preserved unless a processor explicitly
   opts into failed-command handling.
2. **Preservation is centralized:** critical-line recovery and the final size
   gate run after every processor.
3. **Compatibility facades stay thin:** legacy imports delegate to the new core;
   they do not reimplement behavior.
4. **Composition validates ambiguity:** duplicate CLI command names and processor
   registries without a generic fallback fail during construction.
5. **Host adapters do not define domain policy:** hooks translate host payloads
   into calls to application services; they should not accumulate processor- or
   command-family-specific logic.
6. **Command handlers grow vertically:** registry composition and compatibility
   facades must not accumulate command implementation logic.
7. **MCP transport is replaceable:** tool handlers must not depend on JSON-RPC or
   stdio, and protocol routing must consume tools through the registry contract.
8. **Repository orchestration is single-sourced:** host-facing integrations use
   `RepositoryContextService` rather than rebuilding index/ranking/graph flows.
9. **Packing stages stay behaviorally separable:** file ranking, symbol scoring,
   source-window rendering, render/budget helpers, and final assembly may evolve
   independently without moving policy back into compatibility facades.
10. **Scoring does not render:** symbol relevance policy cannot depend on source
    formatting/redaction, while window rendering consumes scoring through the
    extracted scoring stage instead of duplicating its weights.
11. **Graph reranking is post-score:** deterministic file scoring must not depend
    on graph closure or embedding implementations; rerankers consume an already
    scored candidate set and cannot duplicate the lexical scoring pipeline.

`tests/test_architecture_boundaries.py`, `tests/test_hook_runtime.py`,
`tests/test_mcp_server_boundaries.py`, `tests/test_repository_service.py`, and
`tests/test_pack_pipeline_boundaries.py`, `tests/test_symbol_pipeline_boundaries.py`,
and `tests/test_ranking_pipeline_boundaries.py` lock in these extension seams so
future features can grow by composition instead of by adding more central
branching.

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

context/browser/MCP
  -> repository index + ranking + graph services
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

`tests/test_architecture_boundaries.py`, `tests/test_hook_runtime.py`, and
`tests/test_mcp_server_boundaries.py` lock in these extension seams so future
features can grow by composition instead of by adding more central branching.

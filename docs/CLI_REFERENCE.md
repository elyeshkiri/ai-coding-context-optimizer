# CLI reference

Token Saver now exposes one discoverable top-level command surface:

```bash
token-saver --help
token-saver commands
token-saver <command> --help
```

`token-saver --help` lists both registry-backed commands and
legacy-compatible commands. `token-saver commands` lists the registry-backed
surface used for new development. The pages below document **all shipped
commands**, including accepted arguments/options, exit semantics, and structured
output contracts.

For machine-readable fields, see [Machine-readable CLI contracts](JSON_OUTPUTS.md).

## Setup and host lifecycle

- [`setup`](commands/setup.md) — auto-detect/configure Claude Code, Cursor, and Codex.
- [`doctor`](commands/doctor.md) — consolidated CLI/config/host/index health.
- [`uninstall`](commands/uninstall.md) — remove only Token Saver-owned entries.
- [`completion`](commands/completion.md) — generate Bash/Zsh/Fish completion.
- [`commands`](commands/commands.md) — list registry-backed commands.
- [`host-check`](commands/host-check.md) — deeper Claude transport/live-host validation.
- [`serve`](commands/serve.md) — run the local MCP server.
- [`install`](commands/install.md) — legacy/low-level Claude hook installer.

## Repository context and navigation

- [`pack`](commands/pack.md) — build a bounded task-aware context pack.
- [`browse`](commands/browse.md) — inspect ranked candidates/symbols/previews.
- [`impact`](commands/impact.md) — analyze callers/dependencies/tests.
- [`feedback`](commands/feedback.md) — record ranking feedback.
- [`ranking-explain`](commands/ranking-explain.md) — trace ranking score contributions.
- [`map`](commands/map.md) — build a structural repository map.
- [`outline`](commands/outline.md) — show signatures/structure for one source file.
- [`snippet`](commands/snippet.md) — extract one exact symbol body.

## Patch and review workflows

- [`pack-diff`](commands/pack-diff.md) — build bounded context around a Git diff.
- [`review`](commands/review.md) — review a diff using bounded repository evidence.

## Output optimization and recovery

- [`filter`](commands/filter.md) — compress stdin with command-aware processors.
- [`output-explain`](commands/output-explain.md) — explain processor selection/failure routing.
- [`output-replay`](commands/output-replay.md) — replay preservation/savings contracts.
- [`output-benchmark`](commands/output-benchmark.md) — evaluate deterministic output fixtures.
- [`output-policy`](commands/output-policy.md) — generate model-response policy instructions.
- [`output-save`](commands/output-save.md) — compact an already-generated response.
- [`output`](commands/output.md) — page a saved original command result.
- [`outputs-prune`](commands/outputs-prune.md) — prune old saved outputs.
- [`hook`](commands/hook.md) — Claude hook stdin/stdout adapter.

## Measurement and context hygiene

- [`audit`](commands/audit.md) — measure always-on project/user context.
- [`sessions`](commands/sessions.md) — analyze Claude transcript token/tool evidence.
- [`budget`](commands/budget.md) — compare measured context with budget guidance.
- [`policy`](commands/policy.md) — generate lifecycle advice from transcripts.
- [`status`](commands/status.md) — inspect Token Saver's session ledger.
- [`check`](commands/check.md) — CI context-budget/map-freshness check.
- [`estimate`](commands/estimate.md) — estimate/count tokens.
- [`mcp-prune`](commands/mcp-prune.md) — identify/disable unused MCP servers.

## Retrieval validation and ranking regression

- [`evaluate`](commands/evaluate.md) — evaluate retrieval/freeze a holdout definition.
- [`agent-evaluate`](commands/agent-evaluate.md) — evaluate paired agent outcomes.
- [`ranking-snapshot`](commands/ranking-snapshot.md) — save trace-enabled ranking evidence.
- [`ranking-diff`](commands/ranking-diff.md) — compare ranking snapshots.
- [`ranking-calibrate`](commands/ranking-calibrate.md) — aggregate PR ranking history.

## End-to-end experiments

- [`experiment`](commands/experiment.md) — run randomized paired agent trials.
- [`cost-report`](commands/cost-report.md) — analyze paired cost/success evidence.
- [`benchmark`](commands/benchmark.md) — evaluate recorded paired-task evidence.

## Exit-code conventions

The per-command pages are authoritative. Across the CLI, the dominant
convention is:

| Code | Meaning |
|---:|---|
| `0` | Command completed and requested gates passed. |
| `1` | A requested quality/readiness/check condition failed, or required evidence was unavailable. |
| `2` | Invalid input/configuration, malformed evidence, unsafe mutation refused, or argparse usage error. |

Some legacy-compatible commands use `1` for ordinary file/runtime errors; their
pages call this out explicitly.

## Structured output

Commands with JSON output link directly to
[Machine-readable CLI contracts](JSON_OUTPUTS.md), which documents stable
top-level fields, nullability/gating behavior, and compatibility rules for
automation.

## Shell completion

```bash
token-saver completion bash > ~/.local/share/token-saver-completion.bash
token-saver completion zsh
token-saver completion fish
```

Completion intentionally covers top-level commands. Subcommand options remain
discoverable with `token-saver <command> --help`.

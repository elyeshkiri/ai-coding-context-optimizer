# CLI reference

`token-saver commands` prints the registered top-level commands.
`token-saver <command> --help` is the authoritative flag reference.

This page groups commands by task so users do not need to discover the product
from source code.

## Setup and host lifecycle

| Command | Purpose |
|---|---|
| `setup` | Auto-detect/configure Claude Code, Cursor, and Codex. |
| `doctor` | Consolidated CLI/config/host/index health report. |
| `uninstall` | Remove only Token Saver-owned integration entries. |
| `completion` | Generate Bash, Zsh, or Fish completion. |
| `commands` | List registered top-level commands. |
| `host-check` | Deeper Claude host/transport validation, optionally using live evidence. |
| `serve` | Run the local MCP server over stdio. |
| `install` | Legacy/low-level Claude hook installer; prefer `setup` for new installations. |

Typical flow:

```bash
token-saver setup .
token-saver doctor .
```

## Repository context and navigation

| Command | Purpose |
|---|---|
| `browse` | Inspect ranked files/symbols using the production retrieval path. |
| `pack` | Build a bounded evidence-complete context pack for a task. |
| `impact` | Analyze callers/dependencies and likely change impact. |
| `feedback` | Record ranking feedback for later retrieval. |
| `ranking-explain` | Show score contributions and reranker deltas. |
| `map` | Produce a compact structural repository map. |
| `outline` | Show signatures/structure for one source file. |
| `snippet` | Extract one exact symbol body. |

## Patch and review workflows

| Command | Purpose |
|---|---|
| `pack-diff` | Build task context around a patch/diff. |
| `review` | Review a diff using bounded repository evidence. |

## Output optimization and recovery

| Command | Purpose |
|---|---|
| `filter` | Compress stdin using safe command-aware output filtering. |
| `output-explain` | Explain which output processor would handle a command. |
| `output-replay` | Replay captured fixtures against preservation/savings contracts. |
| `output-benchmark` | Evaluate output compaction fixtures. |
| `output-policy` | Generate a compact model-response policy. |
| `output-save` | Compact an already-generated response. |
| `output` | Page an original saved command result without re-running the command. |
| `outputs-prune` | Delete old saved command results. |
| `hook` | Claude hook stdin/stdout adapter; normally invoked by Claude, not manually. |

## Measurement and context hygiene

| Command | Purpose |
|---|---|
| `audit` | Measure always-on context and MCP surface. |
| `sessions` | Analyze Claude transcript token/tool-result evidence. |
| `budget` | Compare a project with Token Saver context-budget guidance. |
| `policy` | Generate lifecycle advice from transcript evidence. |
| `status` | Inspect Token Saver on-disk session state. |
| `check` | CI-friendly context-budget/map freshness check. |
| `estimate` | Estimate/count tokens from a file or stdin. |
| `mcp-prune` | Identify/optionally disable MCP servers unused in transcripts. |

## Retrieval validation and ranking regression

| Command | Purpose |
|---|---|
| `evaluate` | Evaluate retrieval against a task manifest. |
| `agent-evaluate` | Evaluate agent-oriented retrieval evidence. |
| `ranking-snapshot` | Save trace-enabled ranking evidence for a frozen manifest. |
| `ranking-diff` | Compare two saved ranking snapshots. |
| `ranking-calibrate` | Aggregate PR ranking diffs into empirical gate evidence. |

## End-to-end experiments

| Command | Purpose |
|---|---|
| `experiment` | Run randomized paired baseline/Token-Saver agent trials. |
| `cost-report` | Analyze paired run cost/success evidence. |
| `benchmark` | Evaluate a recorded paired-task manifest with supplied rates. |

## Exit-code conventions

Token Saver generally uses:

- `0` — command completed successfully;
- `1` — requested check/condition failed or evidence was unavailable;
- `2` — invalid/conflicting configuration or unsafe mutation was refused.

Individual command help is authoritative where a command has a stricter
contract.

## Machine-readable output

Prefer `--json` where supported for CI/orchestration, including `setup`,
`doctor`, ranking commands, context browsing, and evaluation/reporting
surfaces.

## Discoverability

Generate shell completion:

```bash
token-saver completion bash > ~/.local/share/token-saver-completion.bash
token-saver completion zsh
token-saver completion fish
```

The generated completion intentionally covers top-level commands only; each
subcommand still uses `--help` for flags.

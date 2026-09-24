# `acco learn`

Analyze historical Claude Code sessions and rank evidence-backed token/context
optimization opportunities for one project.

## Synopsis

```bash
acco learn [path] [--days N] [--top N] [--project-only] [--json]
```

Examples:

```bash
acco learn .
acco learn . --days 30 --top 10
acco learn . --project-only --json
```

## Arguments and options

- `path` — project root; default current directory.
- `--days N` — analyze project transcripts modified within this window;
  default 30 days.
- `--top N` — maximum tool rows/opportunities returned; default 8.
- `--project-only` — exclude user-scope Claude instructions when measuring
  current always-on context.
- `--json` — emit the machine-readable report.

`learn` reads local Claude Code project transcripts and current ACCO context
configuration. It does not modify transcripts or send their content to a network
service.

The ranking can surface repeated identical reads, source reads that could begin
with structural outlines, large tool-result families, suspected prompt-cache
recreation, high assistant-output volume, large always-on context, and repeated
identical failed commands.

Evidence classes stay separate:

- provider input/cache/output counters are measured from available transcript
  usage fields;
- tool-result sizes and outline reductions are local token estimates;
- cache recreation is heuristic because usage alone cannot distinguish expiry
  from legitimate prefix changes;
- an opportunity is not automatically avoidable waste or a savings claim.

## Exit codes

- `0` — report produced.
- `2` — invalid window/top/path or no project Claude transcript evidence in
  the requested period.

## Output contract

With `--json`, the report contains `schema`, `root`, `window_days`,
`sessions`, `transcripts`, `turns`, `usage`, `tool_results`,
`behavior`, `duplicate_reads`, `outline`, `cache_recreation`,
`always_on`, `opportunities`, and `evidence`.

Each opportunity includes an id/title, optional
`estimated_tokens_at_stake`, supporting evidence, a concrete action, and a
caution describing the measurement boundary.

See [Machine-readable contracts](../JSON_OUTPUTS.md#learn---json).

## Authoritative runtime help

Run `acco learn --help` for argparse's exact usage text for the installed version.

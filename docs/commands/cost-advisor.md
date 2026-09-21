# `token-saver cost-advisor`

Build a measured local cost-intelligence and efficiency report.

## Synopsis

```bash
token-saver cost-advisor [path] [--days N] [--rates FILE] [--project-only] [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--days N` — telemetry window; default 7 days.
- `--rates SOURCE` — `builtin` for Token Saver's freshness-gated verified registry,
  or an explicit exact-model USD-per-million pricing JSON file.
- `--project-only` — exclude user-scope Claude instructions from the
  always-on context audit.
- `--json` — emit the stable machine-readable report.

The advisor combines measured always-on context, Claude transcript usage/cache
counters, output-budget telemetry, session waste/continuity events, and Token
Saver's observed before/after tool-context savings. The efficiency score is
normalized only over categories with enough evidence; `score.coverage` shows
how much of the 100-point rubric was actually measurable.

Dollar usage cost is emitted only when every priced turn can be mapped to one
exact model id and the supplied rates cover its cache-write TTL breakdown.
Partial pricing is surfaced as partial rather than extrapolated. `--rates builtin`
fails closed once the packaged registry exceeds its freshness window.

## Exit codes

- `0` — report produced;
- `2` — invalid reporting window, unreadable/invalid pricing file, or local
  audit error.

## Output contract

See [Machine-readable contracts](../JSON_OUTPUTS.md#cost-advisor---json).

Operational telemetry does not prove task success or quality. Estimated
tool-context tokens saved are not presented as measured API-dollar savings.

## Authoritative runtime help

Run `token-saver cost-advisor --help` for the installed version.

# `acco savings`

Summarize ACCO's locally observed context-reduction evidence.

## Synopsis

```bash
acco savings [path] [--days N] [--json]
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--days` — positive lookback window; defaults to 30.
- `--json` — emit structured telemetry.

## Exit codes

- `0` — report emitted.
- `2` — invalid window or unreadable local telemetry.

## Output contract

Reports estimated tool/context tokens removed by feature and separately exposes
provider/billed usage counters when observed. Local reductions remain
operational estimates and are not converted into a universal bill-saving or
cost-per-success claim.

## Authoritative runtime help

Run `acco savings --help` for the installed version.

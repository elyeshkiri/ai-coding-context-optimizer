# `acco status`

Show ACCO's simple project health and recent local-efficiency evidence.

## Synopsis

```bash
acco status [path] [--days N] [--json] [--ledger]
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--days` — positive telemetry window; defaults to 7.
- `--json` — emit structured product status.
- `--ledger` — show the historical low-level hook ledger for backward
  compatibility instead of the product status.

The normal status refreshes the structural repository index, so ordinary users
do not need a separate indexing command.

## Exit codes

- `0` — status or legacy ledger emitted.
- `2` — invalid window, project, configuration, or index error.

## Output contract

Product JSON includes readiness, configured hosts, structural-index state,
health, estimated context reduction, waste signals, prefix reuse, continuity
restores, provider calls, and the evidence boundary. `--ledger --json`
returns the legacy state path and raw local ledger structure.

Estimated removed tokens are local before/after context measurements, not an API
invoice or universal cost-per-success figure.

## Authoritative runtime help

Run `acco status --help` for the installed version.

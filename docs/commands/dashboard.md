# `token-saver dashboard`

Show local operational token-efficiency telemetry.

## Synopsis

```bash
token-saver dashboard [path] [--days N] [--json] [--html FILE]
```

## Arguments and options

- `path` — project root; default current directory.
- `--days N` — reporting window; default 7 days.
- `--json` — print the stable machine-readable report.
- `--html FILE` — write a dependency-free local HTML dashboard. No server or
  remote assets are required.

The report separates estimated before/after tool-context savings from exact
Claude transcript usage counters. It also shows continuity restores and
behavioral waste signals. It does **not** infer task success, quality, or a
publishable dollar saving.

## Exit codes

`0` report generated; `2` invalid arguments such as a non-positive window.

## Output contract

See [Machine-readable contracts](../JSON_OUTPUTS.md#dashboard---json).

## Authoritative runtime help

Run `token-saver dashboard --help` for the installed version.

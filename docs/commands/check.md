# `acco check`

CI-friendly context-budget and map-freshness check.

## Synopsis

```bash
acco check [path] [--window N] [--no-user-scope] [--fail-stale-map] [--exact] [--model MODEL]
```

## Arguments and options

- `path` default `.`.
- `--window` default `200000`.
- `--no-user-scope` excludes user config.
- `--fail-stale-map` makes a stale map fail the check.
- `--exact`, `--model` control token counting.

## Exit codes

`0` checks pass; `1` budget/freshness/runtime failure.

## Output contract

Human-readable `OK`/`WARN`/`FAIL` status.

## Authoritative runtime help

Run `acco check --help` for argparse's exact usage text for the installed version.

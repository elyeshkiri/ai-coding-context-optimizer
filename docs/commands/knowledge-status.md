# `acco knowledge-status`

Inspect the size and freshness state of local durable project knowledge without printing the stored claims.

## Synopsis

```bash
acco knowledge-status [path]
acco knowledge-status [path] --json
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--json` — emit machine-readable counters and the private local storage path.

## Exit codes

- `0` — status was read successfully.
- `2` — invalid arguments or local persistence failure.

## Output contract

The report contains `schema`, `total`, `active`, `stale`, `superseded`, and `path`. It intentionally does not expose finding text.

## Authoritative runtime help

```bash
acco knowledge-status --help
```

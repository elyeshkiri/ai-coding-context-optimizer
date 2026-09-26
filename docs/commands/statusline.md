# `acco statusline`

Render a compact one-line operational efficiency status.

## Synopsis

```bash
acco statusline [path] [--days N] [--json]
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--days` — positive telemetry window in days; defaults to 1.
- `--json` — emit the structured status instead of the one-line display.

## Exit codes

- `0` — status emitted.
- `2` — invalid arguments, including a non-positive telemetry window.

## Output contract

Text mode emits one line such as:

```text
ACCO | saved~4.2Kt | waste 1 | prefix 86% | files 3 | HEALTHY
```

JSON exposes health, estimated saved tool-context tokens, waste signals,
continuity restores, current working-file count, prefix reuse rate, provider
calls, and window size. Saved tokens are operational before/after estimates,
not an API invoice or end-to-end cost-per-success claim.

## Authoritative runtime help

Run `acco statusline --help` for the installed version.

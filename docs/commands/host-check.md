# `token-saver host-check`

Validate Claude host configuration, transport, recovery, and optional live evidence.

## Synopsis

```bash
token-saver host-check [path] [--host EXE] [--live-evidence FILE] [--require-ready] [--require-live]
```

## Arguments and options

- `path` default `.`.
- `--host` default `claude`.
- `--live-evidence` points at captured host debug evidence.
- `--require-ready` gates configured hooks + transport recovery.
- `--require-live` gates external-host acceptance evidence.

## Exit codes

`0` report generated and requested gates pass; `1` readiness/live requirement unmet; `2` validation/runtime error.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#host-check-always-json).

## Authoritative runtime help

Run `token-saver host-check --help` for argparse's exact usage text for the installed version.

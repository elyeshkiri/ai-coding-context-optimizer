# `token-saver recovery-status`

Inspect exact-recovery capacity without returning stored source content.

## Synopsis

```bash
token-saver recovery-status [path] [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--json` — emit record/capacity metadata.

## Exit codes

`0` report generated.

## Output contract

Reports database path, record count, used bytes, configured capacity, and
remaining bytes. It never emits recovered payloads.

## Authoritative runtime help

Run `token-saver recovery-status --help` for the installed version.

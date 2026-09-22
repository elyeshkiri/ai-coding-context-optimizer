# `acco recovery-status`

Inspect exact-recovery capacity without returning stored source content.

## Synopsis

```bash
acco recovery-status [path] [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--json` — emit record/capacity metadata.

## Exit codes

`0` report generated.

## Output contract

Reports database path, record count, used bytes, configured capacity, and
remaining bytes. It never emits recovered payloads. v1.13 uses a 512 MiB
per-project default recovery capacity and does not evict older records to admit a
new lossy transform.

## Authoritative runtime help

Run `acco recovery-status --help` for the installed version.

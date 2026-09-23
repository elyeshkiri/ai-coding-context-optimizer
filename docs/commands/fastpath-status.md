# `acco fastpath-status`

Inspect whether the optional Rust acceleration extension is active.

## Synopsis

```bash
acco fastpath-status
acco fastpath-status --json
```

## Arguments and options

- `--json` — emit the backend, accelerated capabilities, and environment override.

Set `ACCO_RUST_FASTPATH=0` to force the Python reference implementation even when the extension is installed.

## Exit codes

- `0` — status reported successfully.

## Output contract

Reports `available`, `backend` (`rust` or `python`), `capabilities[]`, and `env_override`. Absence of the Rust extension is a supported fallback state, not an error.

## Authoritative runtime help

```bash
acco fastpath-status --help
```

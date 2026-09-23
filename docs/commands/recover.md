# `acco recover`

Recover exact bytes saved before a lossy ACCO transformation.

## Synopsis

```bash
acco recover HANDLE [--path PROJECT] [--output FILE] [--json]
```

## Arguments and options

- `HANDLE` — content-addressed `tsr_...` recovery handle.
- `--path PROJECT` — project whose private recovery store contains the handle.
- `--output FILE` — write recovered bytes to a file instead of stdout.
- `--json` — emit metadata plus UTF-8 text or base64 payload.

## Exit codes

`0` exact bytes recovered; `2` invalid/missing handle, integrity failure, or I/O error.

## Output contract

Recovery verifies the stored SHA-256 digest before returning bytes. Binary JSON
output is base64 encoded. Recovery handles are identifiers, not authorization
tokens.

## Authoritative runtime help

Run `acco recover --help` for the installed version.

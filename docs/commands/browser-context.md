# `acco browser-context`

Compress a captured HTML or accessibility-like payload around a task query.

## Synopsis

```bash
acco browser-context INPUT [--path PROJECT] [--query TEXT] [--max-lines N] [--json]
```

## Arguments and options

- `INPUT` — local captured HTML/text file, or `-` for stdin.
- `--path PROJECT` — project root used for exact recovery storage.
- `--query TEXT` — focus terms used to retain nearby visible/actionable context.
- `--max-lines N` — maximum focused lines; default 120.
- `--json` — emit transformation metadata and compressed text.

This command never fetches a URL.

## Exit codes

`0` payload processed; `2` invalid input or I/O error.

## Output contract

A smaller result includes a `tsr_...` exact-recovery handle. If focused output
is not smaller, the original payload is returned unchanged.

## Authoritative runtime help

Run `acco browser-context --help` for the installed version.

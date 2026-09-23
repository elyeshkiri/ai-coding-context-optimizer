# `acco estimate`

Estimate/count tokens in a file or stdin.

## Synopsis

```bash
acco estimate [-f FILE] [--exact] [--model MODEL]
```

## Arguments and options

- `-f/--file` reads a file; otherwise stdin.
- `--exact` uses provider counting.
- `--model` selects exact-counting model.

## Exit codes

`0` success; `1` missing/unreadable file or counting failure.

## Output contract

Plain token count.

## Authoritative runtime help

Run `acco estimate --help` for argparse's exact usage text for the installed version.

# `acco snippet`

Extract one exact symbol body from a source file.

## Synopsis

```bash
acco snippet <file> <symbol> [-q|--quiet]
```

## Arguments and options

- `file` and `symbol` required.
- `-q/--quiet` suppresses auxiliary note.

## Exit codes

`0` success; nonzero when file/symbol extraction fails.

## Output contract

Exact source snippet.

## Authoritative runtime help

Run `acco snippet --help` for argparse's exact usage text for the installed version.

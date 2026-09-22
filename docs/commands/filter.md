# `acco filter`

Compress stdin using command-aware safe output filtering.

## Synopsis

```bash
acco filter [--max-lines N] [--keep-tail N] [--command TEXT]
```

## Arguments and options

- `--max-lines` default `80`.
- `--keep-tail` default `20`.
- `--command` enables command-specific processors.

## Exit codes

`0` success.

## Output contract

Filtered text on stdout.

## Authoritative runtime help

Run `acco filter --help` for argparse's exact usage text for the installed version.

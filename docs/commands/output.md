# `token-saver output`

Page an original saved command result without re-execution.

## Synopsis

```bash
token-saver output <id> [--stream stdout|stderr] [--offset N] [--limit N]
```

## Arguments and options

- `id` saved output id.
- `--stream` default `stdout`.
- `--offset` default `1`.
- `--limit` default `80`.

## Exit codes

`0` success; `1` saved output unavailable/invalid.

## Output contract

Recovered original text.

## Authoritative runtime help

Run `token-saver output --help` for argparse's exact usage text for the installed version.

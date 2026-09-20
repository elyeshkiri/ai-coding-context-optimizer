# `token-saver hook`

Claude Code hook stdin/stdout adapter.

## Synopsis

```bash
token-saver hook
```

## Arguments and options

- No command-line flags; reads Claude hook JSON from stdin.

## Exit codes

`0` normal pass-through/replacement; host-specific errors are surfaced by hook protocol.

## Output contract

Claude hook JSON protocol, not a user-facing report.

## Authoritative runtime help

Run `token-saver hook --help` for argparse's exact usage text for the installed version.

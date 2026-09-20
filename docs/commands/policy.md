# `token-saver policy`

Generate lifecycle advice from Claude transcript evidence.

## Synopsis

```bash
token-saver policy [path] [--all-projects]
```

## Arguments and options

- `path` default `.`.
- `--all-projects` includes all Claude projects.

## Exit codes

`0` success; `1` no transcripts.

## Output contract

Human-readable policy advice + snapshot id.

## Authoritative runtime help

Run `token-saver policy --help` for argparse's exact usage text for the installed version.

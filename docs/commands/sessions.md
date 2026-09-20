# `token-saver sessions`

Analyze real Claude transcripts for token/tool-result evidence.

## Synopsis

```bash
token-saver sessions [path] [--all-projects] [--top N] [--rates FILE]
```

## Arguments and options

- `path` default `.`.
- `--all-projects` searches all Claude project transcripts.
- `--top` default `8`.
- `--rates` optionally prices recorded usage.

## Exit codes

`0` success; `1` no transcripts; `2` pricing error.

## Output contract

Human-readable evidence report.

## Authoritative runtime help

Run `token-saver sessions --help` for argparse's exact usage text for the installed version.

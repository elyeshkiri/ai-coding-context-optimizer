# `acco guardian`

Inspect the most recent structured pre-compaction checkpoint.

## Synopsis

```bash
acco guardian [path] [--json]
```

## Arguments and options

- `path` — project root whose local efficiency snapshot should be inspected; defaults to `.`.
- `--json` — emit the full machine-readable guardian report.

Claude Code's ACCO integration registers a `PreCompact` hook. The checkpoint
contains bounded task class, working-file, recent-command, failure, and
validation metadata. It intentionally does **not** persist raw prompts,
assistant prose, or raw tool output.

## Exit codes

- `0` — report emitted, including the valid `checkpoint: none` state.
- `2` — invalid command-line arguments.

## Output contract

Text mode prints checkpoint availability plus bounded task/file/validation
counts. JSON mode returns `schema`, `root`, `available`, `checkpoint`, and
the privacy contract. On a later `resume` or `compact` start, ACCO may use a
fresh guardian checkpoint as orientation; live repository state remains
authoritative.

## Authoritative runtime help

Run `acco guardian --help` for the installed version.

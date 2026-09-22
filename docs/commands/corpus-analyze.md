# `acco corpus-analyze`

Mine real Claude Code transcripts for high-token Bash command families still using the generic output processor.

## Synopsis

```bash
acco corpus-analyze [path] [--all-projects] [--min-tokens N] [--top N] [--json]
```

## Arguments and options

- `path` — project root used to locate Claude Code transcripts; default current directory.
- `--all-projects` — analyze all locally discoverable Claude project transcripts instead of only the selected project.
- `--min-tokens N` — ignore smaller Bash results; default 100 estimated tokens.
- `--top N` — retain at most N highest-token generic command families; default 20.
- `--json` — emit the complete machine-readable corpus summary.

Raw command arguments are not emitted in the gap report. Commands are reduced to
a family signature such as `git log`, `pnpm run test`, or an executable basename,
so processor prioritization can be data-driven without echoing argument values.

## Exit codes

- `0` — corpus analyzed successfully, including the empty-corpus case.
- `2` — invalid numeric arguments.

## Output contract

The report contains session/Bash-call counts, total output tokens, specialized and
generic output-token totals, specialized coverage, per-processor token volume, and
a bounded `unsupported` array sorted by generic output-token volume.

See [Machine-readable contracts](../JSON_OUTPUTS.md#corpus-analyze---json).

## Authoritative runtime help

Run `acco corpus-analyze --help` for the installed version.

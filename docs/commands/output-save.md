# `token-saver output-save`

Compact an already-generated response deterministically.

## Synopsis

```bash
token-saver output-save [input|-] [--mode terse|normal|detailed] [--max-tokens N] [--enforce-budget] [--structured] [--json]
```

## Arguments and options

- `input` default `-` (stdin).
- `--mode` default `normal`.
- `--max-tokens` overrides budget.
- `--enforce-budget` trims prose while preserving fenced code/diffs.
- `--structured` parses JSON before machine-to-machine compaction.
- `--json` emits metadata + compacted text.

## Exit codes

`0` success; `2` invalid JSON/input/budget.

## Output contract

Compacted text or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#output-save-json).

## Authoritative runtime help

Run `token-saver output-save --help` for argparse's exact usage text for the installed version.

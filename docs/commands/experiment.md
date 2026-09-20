# `token-saver experiment`

Run or dry-run randomized paired agent experiments.

## Synopsis

```bash
token-saver experiment <suite> [--out FILE] [--dry-run] [--allow-development] [--allow-user-hook] [--task ID ...] [--print-task-definition-hash]
```

## Arguments and options

- `suite` required.
- `--out` default `benchmark-runs.json`.
- `--dry-run` validates/prints schedule without model calls.
- `--allow-development` permits unfrozen/narrow suites.
- `--allow-user-hook` permits possible double instrumentation.
- `--task` repeatable task filter.
- `--print-task-definition-hash` prints the freeze hash.

## Exit codes

`0` success; `2` invalid suite/harness configuration.

## Output contract

JSON result/checkpoint; see [Machine-readable contracts](../JSON_OUTPUTS.md#experiment-always-json).

## Authoritative runtime help

Run `token-saver experiment --help` for argparse's exact usage text for the installed version.

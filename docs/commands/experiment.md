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

A production evidence suite may also declare `quality_grader` (judge command,
judge identity, assignment seed, timeout) and `evidence.pricing_file`. Those
fields are carried into run checkpoints for `blind-grade` / `evidence-run`
but do not alter the already-frozen task-definition hash.

## Exit codes

`0` success; `2` invalid suite/harness configuration.

## Output contract

JSON result/checkpoint; see [Machine-readable contracts](../JSON_OUTPUTS.md#experiment-always-json).

Each completed run now embeds transcript-measured fresh input, cache creation
(total plus 5-minute, 1-hour, and unknown-TTL buckets), cache read, output
tokens, model-call count, and tool-call count. Enabled runs isolate Token
Saver state under that run's artifact directory and, when the host executes the
managed hooks, also embed output task/mode/budget telemetry plus a
telemetry-vs-transcript usage-integrity check. This makes the experiment
artifact directly consumable by `agent-evaluate`, `cost-report`,
`output-calibrate`, and `output-effectiveness` without renaming the
experiment-native `enabled` condition.

## Authoritative runtime help

Run `token-saver experiment --help` for argparse's exact usage text for the installed version.

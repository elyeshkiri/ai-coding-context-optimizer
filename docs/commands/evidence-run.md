# `token-saver evidence-run`

Run or resume the complete output evidence pipeline.

## Synopsis

```bash
token-saver evidence-run <suite> [--out FILE] [--rates FILE]
  [--report FILE] [--calibration FILE] [--task ID ...]
  [--allow-development] [--allow-user-hook] [--force-grades]
  [--dry-run] [--require-publishable]
```

## Arguments and options

- `suite` — frozen paired experiment suite.
- `--out` — durable run checkpoint; default `benchmark-runs.json`.
- `--rates` — cache-TTL-aware pricing table. When omitted,
  `evidence.pricing_file` from the suite is used.
- `--report` — effectiveness report destination.
- `--calibration` — quality-gated adaptive budget artifact destination.
- `--task` — repeatable task filter for development/debugging runs.
- `--allow-development` — permit a narrow or unfrozen suite.
- `--allow-user-hook` — permit existing user-level Token Saver hooks.
- `--force-grades` — replace completed blind grades.
- `--dry-run` — validate frozen experiment schedule, grader availability, and pricing.
- `--require-publishable` — exit `1` unless the final effectiveness publication
  gate passes.

Execution is resumable at both the agent-run and blind-grading stages. A normal
run performs: randomized paired experiment → independent verification → blind
A/B response grading → cache-TTL-aware cost/success analysis → output-budget
calibration.

## Exit codes

`0` pipeline completed; `1` `--require-publishable` was requested and the
publication gate failed; `2` invalid suite/configuration/evidence or execution
failure.

## Output contract

The command prints a compact pipeline summary and writes the durable run manifest,
effectiveness report, and calibration artifact. See
[Machine-readable contracts](../JSON_OUTPUTS.md#evidence-run-always-json).

## Authoritative runtime help

Run `token-saver evidence-run --help` for argparse's exact usage text for the
installed version.

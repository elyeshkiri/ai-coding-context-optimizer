# `token-saver output-effectiveness`

Join measured runtime usage, adaptive output-policy telemetry, independently
verified task success, blind response quality, and optional token pricing.

## Synopsis

```bash
token-saver output-effectiveness <manifest> \
  [--fresh-input-per-million F] \
  [--cache-creation-per-million F] \
  [--cache-read-per-million F] \
  [--output-per-million F] \
  [--json] [--require-publishable]
```

## Arguments and options

- `manifest` — paired agent/experiment JSON. Conditions may be
  `baseline` + `token-saver` or the experiment-native
  `baseline` + `enabled`.
- Pricing flags are USD per million tokens for the four measured transcript
  usage categories. A run-level `cost_usd` overrides rate-derived cost.
- `--json` emits the full evidence report.
- `--require-publishable` exits `1` unless all publication gates pass.

For a publishable cost-per-success claim, the manifest must include at least
20 distinct tasks and three trials per task, blind quality scores for every
paired run, no task-success or quality regression, complete optimized-arm
output-policy telemetry that agrees with the copied transcript usage, and
complete positive cost-per-success evidence.

## Exit codes

`0` report produced; `1` requested publishability gate failed; `2`
invalid manifest/pricing/input.

## Output contract

Human summary or JSON. The JSON contains condition usage/cost summaries,
cost-per-success deltas, blind quality parity, telemetry integrity, budget
cohorts, a task-cluster bootstrap confidence interval, and explicit publication
blockers. See [Machine-readable contracts](../JSON_OUTPUTS.md#output-effectiveness-json).

## Authoritative runtime help

Run `token-saver output-effectiveness --help` for argparse's exact usage text
for the installed version.

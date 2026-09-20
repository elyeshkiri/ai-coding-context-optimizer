# `token-saver output-effectiveness`

Join measured runtime usage, adaptive output-policy telemetry, independently
verified task success, blind response quality, and optional token pricing.

## Synopsis

```bash
token-saver output-effectiveness <manifest> \
  [--fresh-input-per-million F] \
  [--cache-creation-5m-per-million F] \
  [--cache-creation-1h-per-million F] \
  [--cache-creation-unknown-per-million F] \
  [--cache-read-per-million F] \
  [--output-per-million F] \
  [--json] [--require-publishable]
```

## Arguments and options

- `manifest` — paired agent/experiment JSON. Conditions may be
  `baseline` + `token-saver` or the experiment-native
  `baseline` + `enabled`.
- Pricing flags are USD per million tokens for fresh input, 5-minute cache
  creation, 1-hour cache creation, unknown-TTL cache creation, cache reads, and
  output. A run-level `cost_usd` overrides rate-derived cost. If a nonzero
  usage category has no corresponding rate, derived cost is incomplete rather
  than silently treating that category as free.
- `--json` emits the full evidence report.
- `--require-publishable` exits `1` unless all publication gates pass.

For a publishable cost-per-success claim, the manifest must include at least
20 distinct tasks and three trials per task. Token Saver recomputes
`protocol.task_definition_sha256`, checks each run's model/revision/prompt hash
against the frozen suite, requires blind quality scores for every paired run,
no task-success or quality regression, and complete optimized-arm policy
telemetry with at least one measured turn plus a concrete task/mode/budget.
Telemetry must agree with the copied transcript. The cost-per-success point
estimate must improve **and** the task-cluster 95% confidence interval must
remain strictly above zero.

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

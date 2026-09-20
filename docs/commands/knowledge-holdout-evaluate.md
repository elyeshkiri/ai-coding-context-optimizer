# `token-saver knowledge-holdout-evaluate`

Evaluate an already-run, independently verified, blind-graded knowledge-efficiency manifest without rerunning agents.

## Synopsis

```bash
token-saver knowledge-holdout-evaluate knowledge-holdout-runs.json \
  --rates benchmarks/claude-sonnet-5-rates-2026-09-19.json \
  --json --require-publishable
```

## Arguments and options

- positional `manifest` — paired knowledge-holdout run artifact.
- `--rates FILE` — required cache-TTL-aware rate evidence.
- `--model NAME` — override model identity when absent from the manifest runner.
- `--json` — emit the full report.
- `--require-publishable` — return 1 unless all publication gates pass.

## Exit codes

- `0` — evaluation completed and any requested gate passed.
- `1` — the report is valid but the requested publication gate is blocked.
- `2` — invalid/missing evidence, rates, pairing, or protocol identity.

## Output contract

The report includes condition summaries, reductions in tool calls/input tokens/duplicate reads/cost per success, task-cluster bootstrap intervals, treatment/control feature activation, blind quality evidence, protocol identity, and explicit publication blockers.

## Authoritative runtime help

```bash
token-saver knowledge-holdout-evaluate --help
```

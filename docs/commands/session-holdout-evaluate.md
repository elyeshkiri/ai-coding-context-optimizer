# `token-saver session-holdout-evaluate`

Evaluate an already executed and blind-graded session-efficiency manifest
without rerunning paid agents or cloning benchmark repositories.

## Synopsis

```bash
token-saver session-holdout-evaluate <manifest>
  --rates FILE [--model MODEL] [--json] [--require-publishable]
```

## Options

- `--rates FILE` — cache-TTL-aware model pricing table.
- `--model MODEL` — override the model key; otherwise use `runner.model`.
- `--json` — emit the complete machine-readable report.
- `--require-publishable` — exit `1` if the strict publication gate fails.

The evaluator recomputes session metrics from fields already captured from raw
transcripts, applies independent task/blind-quality evidence, calculates
tool-call/input-token/retry/cost-per-success reductions, and task-cluster
bootstrap confidence intervals.

Token Saver intervention counts are surfaced only under `feature_activation`.
They prove treatment exposure but do not replace transcript-derived outcome
metrics.

## Exit codes

- `0` — evaluation completed and any requested gate passed.
- `1` — requested publication gate blocked.
- `2` — invalid/incomplete manifest, pricing, or arguments.

## Authoritative runtime help

Run `token-saver session-holdout-evaluate --help` for the installed version.

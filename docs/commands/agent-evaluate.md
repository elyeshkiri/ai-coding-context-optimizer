# `token-saver agent-evaluate`

Evaluate paired baseline/Token Saver agent outcomes.

## Synopsis

```bash
token-saver agent-evaluate <manifest>
```

## Arguments and options

- `manifest` — paired agent-run JSON. Runs are paired by `task` + `trial`;
  `trial` defaults to `1` for legacy manifests. Optimized runs may use
  condition `token-saver` or experiment-native `enabled`.
- Runs may optionally include blind response-quality scores for `correctness`,
  `completeness`, `actionability`, `safety`, and `concision`, plus a
  boolean `blocker`. When supplied, every paired run must be scored and the
  manifest must declare `quality_evaluation.blinded`.

## Exit codes

`0` success; `2` invalid/missing manifest.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#agent-evaluate-always-json).
The command always reports descriptive token measurements when denominators are
available. A publishable savings claim is allowed only with blind quality
evidence, task-success parity, quality parity, and an available per-success
comparison. `claim_blockers` explains every failed gate. Multi-trial reports
also include deterministic paired-distribution summaries and a 95% bootstrap
confidence interval.

## Authoritative runtime help

Run `token-saver agent-evaluate --help` for argparse's exact usage text for the installed version.

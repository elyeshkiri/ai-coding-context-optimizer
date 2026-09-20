# `token-saver agent-evaluate`

Evaluate paired baseline/Token Saver agent outcomes.

## Synopsis

```bash
token-saver agent-evaluate <manifest>
```

## Arguments and options

- `manifest` — paired agent-run JSON.
- Runs may optionally include blind response-quality scores for `correctness`,
  `completeness`, `actionability`, `safety`, and `concision`, plus a
  boolean `blocker`. When supplied, every paired run must be scored and the
  manifest must declare `quality_evaluation.blinded`.

## Exit codes

`0` success; `2` invalid/missing manifest.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#agent-evaluate-always-json).
Savings are suppressed when task success regresses or, when quality evidence is
present, the blind quality parity gate fails.

## Authoritative runtime help

Run `token-saver agent-evaluate --help` for argparse's exact usage text for the installed version.

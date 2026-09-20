# `token-saver session-holdout`

Run or resume the frozen session-efficiency experiment, blind grading, and
effectiveness evaluation.

## Synopsis

```bash
token-saver session-holdout <suite>
  [--out FILE] [--rates FILE] [--report FILE]
  [--task ID ...] [--force-grades]
  [--allow-development] [--allow-user-hook]
  [--dry-run] [--require-publishable]
```

## Arguments and options

- `suite` — frozen session-efficiency suite JSON.
- `--out FILE` — durable run checkpoint; default `session-holdout-runs.json`.
- `--rates FILE` — explicit cache-TTL-aware pricing table; otherwise use the
  suite's `evidence.pricing_file`.
- `--report FILE` — effectiveness report destination.
- `--task ID` — repeatable frozen-task filter for development/debugging.
- `--force-grades` — replace complete existing blind grades.
- `--allow-development` — permit a narrow/unfrozen smoke suite while retaining
  condition-isolation validation.
- `--allow-user-hook` — permit an existing user-level Token Saver hook.
- `--dry-run` — validate schedule, profiles, grader, and pricing without paid
  agent calls.
- `--require-publishable` — exit `1` if the final strict publication gate
  is blocked.

## What it compares

The shipped frozen suite compares two profiles of the **same current Token Saver
binary**:

- `v1.6-session-baseline` — Token Saver installed, session efficiency master,
  continuity, cross-turn dedup, and waste detection disabled.
- `v1.7-session-efficiency` — the same binary with those four switches enabled.

The baseline therefore emulates the 1.6 **session behavior** while holding
retrieval/output code, model, task revision, prompt, and verifier constant. It is
not a historical 1.6 package checkout.

Each arm uses two fresh Claude sessions: investigation-only phase 1, then a real
`SessionStart:resume` hook boundary, then implementation phase 2. The runner
fails if phase 1 changes repository state.

## Evidence

The run manifest records exact transcript usage plus independently derived:

- total tool calls;
- Bash calls and unique commands;
- repeated command calls;
- identical-failure retry attempts;
- duplicate full-file Reads.

Treatment-side Token Saver events are recorded separately to prove continuity,
dedup, and waste mechanisms actually fired; they are not used as outcome truth.

## Publication gate

`--require-publishable` exits `1` unless the broad frozen design, pair
identity, independent task success, blind quality parity, control isolation,
feature activation, complete pricing, positive cost-per-success reduction, and
strictly positive task-cluster 95% cost/success CI all pass.

## Output contract

The command always prints JSON. Dry-run output contains the comparison labels,
resolved condition profiles, randomized schedule, grader identity, and pricing
source. Completed runs write the durable run manifest plus a
`*.session-effectiveness.json` report containing condition totals, reductions,
task-cluster confidence intervals, feature activation, blind quality, protocol
integrity, and publication blockers. See
[Machine-readable contracts](../JSON_OUTPUTS.md#session-holdout-always-json).

## Exit codes

- `0` — completed; requested publication gate passed or was not requested.
- `1` — `--require-publishable` requested but the final gate was blocked.
- `2` — invalid suite/evidence/configuration or execution failure.

## Authoritative runtime help

Run `token-saver session-holdout --help` for the installed version.

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

## Exit codes

- `0` — completed; requested publication gate passed or was not requested.
- `1` — `--require-publishable` requested but the final gate was blocked.
- `2` — invalid suite/evidence/configuration or execution failure.

## Authoritative runtime help

Run `token-saver session-holdout --help` for the installed version.

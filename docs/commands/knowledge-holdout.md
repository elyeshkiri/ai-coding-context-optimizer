# `acco knowledge-holdout`

Run/resume the frozen paired multi-session experiment for knowledge-assisted read avoidance plus the cache-economics gate.

## Synopsis

```bash
acco knowledge-holdout \
  benchmarks/knowledge-efficiency-swebench-24.frozen.json \
  --out knowledge-holdout-runs.json \
  --require-publishable
```

## Arguments and options

- positional `suite` — frozen/development experiment definition.
- `--out FILE` — resumable paired-run manifest.
- `--rates FILE` — cache-TTL-aware model pricing; otherwise use suite evidence metadata.
- `--report FILE` — effectiveness report destination.
- `--task ID` — restrict execution to a task; repeatable.
- `--force-grades` — recompute blind response grades.
- `--dry-run` — validate/schedule without paid model execution.
- `--allow-development` — allow an unfrozen/smaller diagnostic suite.
- `--allow-user-hook` — permit an existing user ACCO hook.
- `--require-publishable` — exit nonzero unless the strict publication gate passes.

The frozen protocol uses the same 24 SWE-bench Verified tasks and three trials per task. Both arms run the same current ACCO build, both explicitly create verified findings during phase 1, and both start phase 2 as a fresh session. Continuity, cross-turn dedup, and waste detection are disabled in both arms. Only knowledge read avoidance and cache-economics gating differ.

## Exit codes

- `0` — requested pipeline stage completed and any requested publication gate passed.
- `1` — `--require-publishable` was requested but the gate is blocked.
- `2` — malformed suite/evidence, runner failure, invalid pricing, or unsafe experiment configuration.

## Output contract

The completion summary contains suite/run/report paths, task and paired-trial counts, reductions, feature activation, publication blockers, and `claim_allowed`.

No savings percentage is publishable merely because the frozen definition exists. The paid paired run must complete and pass task-success, blind-quality, feature-exposure, cost-evidence, and confidence-interval gates.

## Authoritative runtime help

```bash
acco knowledge-holdout --help
```

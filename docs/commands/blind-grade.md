# `token-saver blind-grade`

Blind-grade paired experiment final responses with deterministic A/B relabeling.

## Synopsis

```bash
token-saver blind-grade <manifest> [--out FILE] [--force] [--dry-run]
```

## Arguments and options

- `manifest` — paired experiment/result JSON containing frozen tasks, transcripts,
  and a `quality_grader` configuration.
- `--out FILE` — write a separate graded manifest instead of updating the input.
- `--force` — replace complete existing grades with fresh judge calls.
- `--dry-run` — validate pair coverage and print the deterministic A/B assignment
  plan without calling the grader.

The grader receives only the frozen task plus anonymized Response A / Response B.
Condition names are never included in the grading request. Position assignment is
seeded and balanced across the full pair set. Completed pairs are checkpointed and
reused on resume.

## Exit codes

`0` grading completed or dry-run succeeded; `2` malformed evidence, invalid
grader output, timeout, partial existing grades, or grader execution failure.

## Output contract

The graded manifest retains all experiment fields, adds `quality` and `blocker`
to every run, and adds `quality_evaluation` plus hashed `blind_grading` audit
records. See [Machine-readable contracts](../JSON_OUTPUTS.md#blind-grade-always-json).

## Authoritative runtime help

Run `token-saver blind-grade --help` for argparse's exact usage text for the
installed version.

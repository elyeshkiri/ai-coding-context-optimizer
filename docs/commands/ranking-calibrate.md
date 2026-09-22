# `acco ranking-calibrate`

Aggregate saved PR ranking diffs into empirical gate evidence.

## Synopsis

```bash
acco ranking-calibrate <history> [--ground-truth-sha HASH] [--min-reports N] [--json | --markdown]
```

## Arguments and options

- `history` file/directory of ranking-diff reports.
- `--ground-truth-sha` selects one frozen cohort.
- `--min-reports` default `20`.
- Output is JSON by default; `--markdown` emits a GitHub-ready report.

## Exit codes

`0` success; `2` malformed/invalid history.

## Output contract

JSON or Markdown; see [Machine-readable contracts](../JSON_OUTPUTS.md#ranking-calibrate-json-by-default).

## Authoritative runtime help

Run `acco ranking-calibrate --help` for argparse's exact usage text for the installed version.

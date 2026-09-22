# `acco ranking-diff`

Compare baseline/candidate ranking snapshots with stage attribution.

## Synopsis

```bash
acco ranking-diff <baseline> <candidate> [--json | --markdown] [--fail-on-regression] [--allowed-rank-drop N]
```

## Arguments and options

- `baseline`, `candidate` snapshot files.
- `--json` structured report; `--markdown` GitHub-ready summary.
- `--fail-on-regression` enables exit-code gating.
- `--allowed-rank-drop` default `0`.

## Exit codes

`0` comparison completed/no gated violation; `1` gated regression violation; `2` incompatible/malformed snapshots.

## Output contract

Human/JSON/Markdown; see [Machine-readable contracts](../JSON_OUTPUTS.md#ranking-diff-json).

## Authoritative runtime help

Run `acco ranking-diff --help` for argparse's exact usage text for the installed version.

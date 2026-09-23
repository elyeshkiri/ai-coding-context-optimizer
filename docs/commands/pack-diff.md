# `acco pack-diff`

Build bounded repository context around a Git diff.

## Synopsis

```bash
acco pack-diff [path] [--base REV] [--staged] [--json] [--max-tokens N]
```

## Arguments and options

- `path` default `.`.
- `--base` default `HEAD`.
- `--staged` uses staged changes.
- `--max-tokens` default `6000`.
- `--json` emits context + coverage metadata.

## Exit codes

`0` success; `2` invalid diff/context request.

## Output contract

Context/coverage text or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#pack-diff-json).

## Authoritative runtime help

Run `acco pack-diff --help` for argparse's exact usage text for the installed version.

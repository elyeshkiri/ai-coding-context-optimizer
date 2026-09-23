# `acco outputs-prune`

Delete saved command results older than a threshold.

## Synopsis

```bash
acco outputs-prune [--days DAYS]
```

## Arguments and options

- `--days` default `7`; must be nonnegative.

## Exit codes

`0` success; argparse validation/error exits nonzero.

## Output contract

Removal count.

## Authoritative runtime help

Run `acco outputs-prune --help` for argparse's exact usage text for the installed version.

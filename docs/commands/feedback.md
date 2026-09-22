# `acco feedback`

Record useful/irrelevant ranking feedback for one file.

## Synopsis

```bash
acco feedback <file> [--path PATH] (--useful | --irrelevant)
```

## Arguments and options

- `file` repository-relative file.
- `--path` default `.`.
- Exactly one of `--useful` or `--irrelevant` is required.

## Exit codes

`0` success; argparse usage errors exit `2`.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#feedback-always-json).

## Authoritative runtime help

Run `acco feedback --help` for argparse's exact usage text for the installed version.

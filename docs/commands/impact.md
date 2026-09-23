# `acco impact`

Analyze callers/dependencies/tests affected by a file or symbol.

## Synopsis

```bash
acco impact <target> [--path PATH] [--json]
```

## Arguments and options

- `target` file path or symbol.
- `--path` default `.`.
- `--json` emits structured impact.

## Exit codes

`0` success; `2` no match/invalid target.

## Output contract

Human impact list or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#impact-json).

## Authoritative runtime help

Run `acco impact --help` for argparse's exact usage text for the installed version.

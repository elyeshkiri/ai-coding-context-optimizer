# `token-saver output-policy`

Generate compact model-response policy instructions.

## Synopsis

```bash
token-saver output-policy [--mode terse|normal|detailed] [--max-tokens N] [--json]
```

## Arguments and options

- `--mode` default `normal`.
- `--task` adapts instructions and the default budget for `general`, `coding`, `debugging`, `review`, `explanation`, or `planning`.
- `--max-tokens` overrides both mode and task defaults.
- `--json` emits policy fields, including the resolved task.

## Exit codes

`0` success; `2` invalid budget/mode.

## Output contract

Instructions or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#output-policy-json).

## Authoritative runtime help

Run `token-saver output-policy --help` for argparse's exact usage text for the installed version.

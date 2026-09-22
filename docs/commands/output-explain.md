# `acco output-explain`

Explain which output processor handles a command/failure.

## Synopsis

```bash
acco output-explain <command> [--exit-code N] [--sample FILE]
```

## Arguments and options

- `command` original command string.
- `--exit-code` optional process status.
- `--sample` optional captured output file used for failure detection.

## Exit codes

`0` success; `2` unreadable sample.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#output-explain-always-json).

## Authoritative runtime help

Run `acco output-explain --help` for argparse's exact usage text for the installed version.

# `token-saver output-replay`

Replay captured output fixtures against preservation/savings contracts.

## Synopsis

```bash
token-saver output-replay <manifest>
```

## Arguments and options

- `manifest` quality-contract JSON.

## Exit codes

`0` all cases pass; `1` one or more quality contracts fail; `2` malformed/unreadable manifest.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#output-replay-always-json).

## Authoritative runtime help

Run `token-saver output-replay --help` for argparse's exact usage text for the installed version.

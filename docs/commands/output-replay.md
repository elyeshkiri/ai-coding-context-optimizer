# `acco output-replay`

Replay captured output fixtures against preservation/savings contracts.

## Synopsis

```bash
acco output-replay <manifest> [--require-frozen] [--print-definition-hash]
```

## Arguments and options

- `manifest` quality-contract JSON.
- `--require-frozen` — require `protocol.frozen=true`, `frozen_at`, and an
  exact SHA-256 of the case definition.
- `--print-definition-hash` — print the canonical case-definition SHA-256
  without running compression.

## Exit codes

`0` all cases pass; `1` one or more quality contracts fail; `2` malformed/unreadable manifest.

## Output contract

Always JSON. Cases can require exact `must_preserve` strings and
`must_not_contain` strings; the latter fail only when a transformation
introduces text that was absent from the original. See
[Machine-readable contracts](../JSON_OUTPUTS.md#output-replay-always-json).

## Authoritative runtime help

Run `acco output-replay --help` for argparse's exact usage text for the installed version.

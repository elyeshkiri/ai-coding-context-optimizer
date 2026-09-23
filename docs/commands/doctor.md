# `acco doctor`

Consolidate CLI/config/host/index/transcript health.

## Synopsis

```bash
acco doctor [path] [--json] [--no-index] [--require-ready]
```

## Arguments and options

- `path` default `.`.
- `--json` emits structured health.
- `--no-index` skips repository-index health.
- `--require-ready` returns nonzero when overall readiness is false.

## Exit codes

`0` report generated and, when required, ready; `1` with `--require-ready` when not ready; `2` invalid path/config.

## Output contract

Human health report or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#doctor-json).

## Authoritative runtime help

Run `acco doctor --help` for argparse's exact usage text for the installed version.

# `token-saver cost-report`

Compare cost/success evidence from paired run files.

## Synopsis

```bash
token-saver cost-report <baseline> [optimized] [--input-per-million F] [--output-per-million F] [--cached-input-per-million F] [--allow-unpaired] [--json]
```

## Arguments and options

- Single-file mode accepts paired agent runs; optimized runs may use
  `token-saver` or experiment-native `enabled`. Two-file mode compares
  separate baseline/optimized files.
- Pricing flags default to `0.0`.
- `--allow-unpaired` is only valid in two-file mode.
- `--json` emits the full comparison.

## Exit codes

`0` success; `2` invalid pairing/pricing/input.

## Output contract

Human summary or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#cost-report-json).

## Authoritative runtime help

Run `token-saver cost-report --help` for argparse's exact usage text for the installed version.

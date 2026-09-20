# `token-saver output-calibrate`

Build a reusable adaptive output-budget calibration artifact from blinded paired
agent runs.

## Synopsis

```bash
token-saver output-calibrate <manifest> [--margin 1.15] [--out FILE]
```

## Arguments and options

- `manifest` — paired agent-run JSON containing blind response-quality scores.
- `--margin` — multiplicative safety margin above observed p90 output tokens;
  default `1.15`, allowed range `1.0..2.0`.
- `--out` — write the JSON calibration artifact to a file instead of stdout.

Token Saver runs intended for calibration should include `output_task` and
`output_mode`. A task/mode recommendation requires at least three paired runs
where both conditions succeeded, the Token Saver response has no blocker, and
blind correctness/safety/weighted quality remain at parity.

Failed, blocked, unblinded, malformed, and materially lower-quality responses do
not teach the adaptive controller.

## Exit codes

`0` success; `2` invalid manifest, calibration margin, or file operation.

## Output contract

The JSON artifact contains schema/version metadata and per-task/per-mode
recommendations with sample count, observed p90 output tokens, safety margin,
and recommended token budget. Save it as
`.token-saver.output-calibration.json` (or configure another path) for automatic
Claude prompt-time budgeting.

## Authoritative runtime help

Run `token-saver output-calibrate --help` for argparse's exact usage text for
the installed version.

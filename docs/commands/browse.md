# `token-saver browse`

Inspect ranked repository candidates, symbols, previews, and details.

## Synopsis

```bash
token-saver browse [path] --query TEXT [--max-files N] [--preview-tokens N] [--detail-tokens N] [--show N] [--interactive] [--json] [--no-changed-boost]
```

## Arguments and options

- `path` default `.`.
- `--query` required.
- `--max-files` default `8`.
- `--preview-tokens` default `350`.
- `--detail-tokens` default `1200`.
- `--show N` prints one candidate detail.
- `--interactive` opens list/show/quit prompt.
- `--json` emits structured output.
- `--no-changed-boost` disables changed-file ranking boost.

## Exit codes

`0` success; `2` invalid repository/query or out-of-range `--show`.

## Output contract

Human browser or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#browse-json).

## Authoritative runtime help

Run `token-saver browse --help` for argparse's exact usage text for the installed version.

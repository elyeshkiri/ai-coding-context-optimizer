# `token-saver ranking-explain`

Explain deterministic and post-score contributions for ranked files.

## Synopsis

```bash
token-saver ranking-explain [path] --query TEXT [--max-files N] [--json] [--no-changed-boost] [--semantic]
```

## Arguments and options

- `path` default `.`.
- `--query` required.
- `--max-files` default `8`.
- `--json` emits trace data.
- `--no-changed-boost` disables changed-file boost.
- `--semantic` includes persistent chunk-level semantic hits and hybrid-RRF score transitions.

## Exit codes

`0` success; `2` invalid repository/query.

## Output contract

Human score trace or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#ranking-explain-json).

## Authoritative runtime help

Run `token-saver ranking-explain --help` for argparse's exact usage text for the installed version.

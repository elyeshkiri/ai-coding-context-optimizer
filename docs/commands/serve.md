# `token-saver serve`

Run the local MCP server over stdio.

## Synopsis

```bash
token-saver serve [path]
```

## Arguments and options

- `path` repository root, default `.`.

## Exit codes

Runs until the MCP transport closes; startup/protocol errors are nonzero.

## Output contract

JSON-RPC over stdio; not a human report.

## Authoritative runtime help

Run `token-saver serve --help` for argparse's exact usage text for the installed version.

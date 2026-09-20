# `token-saver mcp-prune`

Identify and optionally disable MCP servers unused in transcripts.

## Synopsis

```bash
token-saver mcp-prune [path] [--apply] [--force]
```

## Arguments and options

- `path` default `.`.
- `--apply` writes `disabledMcpServers`.
- `--force` permits apply when no MCP tool evidence was observed.

## Exit codes

`0` success/dry-run; `1` no transcript evidence; `2` unsafe apply refused without `--force`.

## Output contract

Human-readable server list/status.

## Authoritative runtime help

Run `token-saver mcp-prune --help` for argparse's exact usage text for the installed version.

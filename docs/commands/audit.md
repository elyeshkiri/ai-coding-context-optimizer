# `token-saver audit`

Measure always-on project/user context and optional MCP schemas.

## Synopsis

```bash
token-saver audit [path] [--window N] [--no-user-scope] [--probe-mcp] [--mcp-timeout N] [--exact] [--model MODEL]
```

## Arguments and options

- `path` default `.`.
- `--window` default `200000`.
- `--no-user-scope` excludes user Claude config.
- `--probe-mcp` launches configured MCP servers to measure schemas.
- `--mcp-timeout` default `15`.
- `--exact` uses provider counting instead of estimation.
- `--model` selects the model for exact counting.

## Exit codes

`0` success; `1` measurement/runtime failure.

## Output contract

Human-readable report.

## Authoritative runtime help

Run `token-saver audit --help` for argparse's exact usage text for the installed version.

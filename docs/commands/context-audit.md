# `acco context-audit`

Audit cross-host always-on and on-demand instruction context without mutating it.

## Synopsis

```bash
acco context-audit [path] [--project-only] [--probe-mcp]
  [--mcp-timeout SECONDS] [--json]
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--project-only` — omit user-scope Claude instructions.
- `--probe-mcp` — launch configured MCP servers long enough to measure advertised schemas.
- `--mcp-timeout` — MCP probe timeout in seconds; defaults to 15.
- `--json` — emit the complete structured report.

The audit covers Claude instructions/rules/memory/skills plus `AGENTS.md`,
`GEMINI.md`, Copilot instructions, Cursor rules, portable agent skills, and
configured MCP servers. It identifies oversized files and exact duplicate
instruction bodies but does not edit them.

## Exit codes

- `0` — audit completed.
- `2` — invalid input or an audit/MCP probe error.

## Output contract

Text mode reports always-on token estimate, item/oversized/duplicate counts, and
recommendations. JSON includes `items`, `duplicates`, `oversized`,
`mcp_servers`, optional `mcp_probe`, recommendations, and
`mutates_files: false`. Recommendations are optimization hypotheses, not
automatic edits.

## Authoritative runtime help

Run `acco context-audit --help` for the installed version.

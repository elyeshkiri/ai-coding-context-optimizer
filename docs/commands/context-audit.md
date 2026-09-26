# `acco context-audit`

Audit cross-host always-on and on-demand instruction context without mutating it.

```bash
acco context-audit .
acco context-audit . --project-only
acco context-audit . --probe-mcp
acco context-audit . --json
```

The audit includes Claude instructions/rules/memory/skills plus AGENTS.md,
GEMINI.md, Copilot instructions, Cursor rules, portable agent skills, and
configured MCP servers. It reports oversized instruction files and exact
duplicate bodies. `--probe-mcp` launches configured MCP servers to measure
their advertised schema cost.

Recommendations are hypotheses for cleanup; this command never edits files.

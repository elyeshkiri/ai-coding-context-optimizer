# `acco audit`

Run one consolidated evidence-oriented audit across ACCO optimization layers.

## Synopsis

```bash
acco audit [path] [--days N] [--window N] [--no-user-scope] [--probe-mcp]
                  [--mcp-timeout N] [--client CLIENT] [--rates SOURCE]
                  [--top N] [--min-processor-tokens N] [--exact] [--model MODEL]
                  [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--days N` — operational telemetry window; default 7 days.
- `--window N` — context-window denominator; default 200000.
- `--no-user-scope` / `--project-only` — exclude user-scope Claude instructions.
- `--probe-mcp` — launch configured stdio MCP servers and measure their tool schemas.
- `--mcp-timeout N` — per-server probe timeout; default 15 seconds.
- `--client CLIENT` — include conservative host capability evidence for a selected client.
- `--rates SOURCE` — `builtin` or an explicit exact-model pricing JSON file.
- `--top N` — maximum unsupported command families to retain; default 10.
- `--min-processor-tokens N` — ignore smaller Bash results in processor coverage analysis; default 100.
- `--exact` — use exact provider counting for context files when configured.
- `--model MODEL` — exact-counting model.
- `--json` — emit the machine-readable cross-layer report.

The consolidated audit preserves the historical context/MCP measurements and adds
semantic-index state, Rust/Python fastpath state, transcript-observed specialized
processor coverage, exact-recovery capacity, operational efficiency telemetry, and
evidence-linked recommendations.

## Exit codes

- `0` — report produced successfully.
- `2` — invalid input/configuration or a required local measurement failed.

## Output contract

Human output is a compact cross-layer status report. JSON output contains `context`,
`efficiency`, `retrieval`, `fastpath`, `processor_coverage`, `client_capabilities`,
`recovery`, `recommendations`, and an explicit `evidence` boundary.

Operational token counts and transform estimates are not promoted to task-success,
quality-preservation, or end-to-end cost-per-success claims. See
[Machine-readable contracts](../JSON_OUTPUTS.md#audit---json).

## Authoritative runtime help

Run `acco audit --help` for argparse's exact usage text for the installed version.

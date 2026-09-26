# Everyday efficiency surfaces

ACCO keeps retrieval first, but the everyday product now covers six adjacent
cost surfaces without giving multiple components ownership of the same bytes.

## 1. Compaction Guardian

Claude Code installs an ACCO `PreCompact` hook. Before compaction ACCO snapshots
only bounded structured state: task class, working files, recent commands,
failures, and validations. Raw prompts, assistant prose, and raw tool output are
not stored by the guardian.

Inspect the checkpoint:

```bash
acco guardian .
```

On a later `resume` or `compact` session start, ACCO can restore the checkpoint
as orientation. Live repository state remains authoritative.

## 2. Ephemeral provider wrapper

Run a supported host through ACCO's provider boundary without manually exporting
base URLs:

```bash
acco wrap claude -- --help
acco wrap codex -- --help
acco wrap gemini -- --help
```

Or use the short aliases:

```bash
acco claude
acco codex
acco gemini
```

The wrapper starts a loopback-only provider proxy, launches the child process
with the provider's base-URL environment variable, and tears the proxy down when
the child exits. Routing remains off unless explicitly enabled:

```bash
acco wrap --model-routing calibrated claude
```

Use `--dry-run` to inspect the launch plan. Unknown agents are supported only
when `--provider`, `--upstream`, and `--base-url-env` are supplied explicitly.

## 3. Portable Lean Skill

Print the skill:

```bash
acco lean-skill
```

Install for Claude or the portable `.agents/skills` convention:

```bash
acco lean-skill . --install --host claude
acco lean-skill . --install --host agents
acco lean-skill . --install --host all
```

Lean mode constrains final prose only. It explicitly forbids skipping
investigation or verification to save tokens.

## 4. Payload-aware compression

The normal output pipeline still gives command-specific processors first
priority. When the command is unknown, ACCO can now recognize large JSON,
unified diffs, leveled logs, and large Markdown tables.

The transforms are conservative:

- Browser/page payloads reuse ACCO's structural/actionable browser focusing.\n- JSON keeps object/scalar structure and bounds large arrays.
- Diff compression removes unchanged context but preserves every changed line.
- Generic logs keep diagnostics plus bounded head/tail context.
- Tables keep the header and both edges.

When used through ACCO hooks/provider transforms, the pre-transform payload
remains available through ACCO recovery.

## 5. Cross-host context audit

```bash
acco context-audit .
acco context-audit . --probe-mcp
```

The audit covers Claude instructions/rules/memory/skills plus AGENTS.md,
GEMINI.md, Copilot instructions, Cursor rules, portable agent skills, and
configured MCP servers. It reports oversized files and exact duplicate
instruction bodies but does not edit them.

## 6. Live status line

```bash
acco statusline .
```

Example:

```text
ACCO | saved~4.2Kt | waste 1 | prefix 86% | files 3 | HEALTHY
```

The line uses local operational telemetry only. Saved tokens are estimated
before/after tool-context reductions, not an API-billing or cost-per-success
claim.

## Layer ownership

The intended stack remains:

```text
repository evidence -> ACCO retrieval
session lifecycle   -> ACCO continuity / guardian
provider boundary   -> ACCO proxy (optional)
tool output         -> one ACCO compression owner
final prose         -> ACCO Lean policy
observability       -> dashboard / statusline / learn
```

Do not put multiple lossy compressors on the same tool-output path. Exact
recovery is easiest to reason about when one component owns each boundary.

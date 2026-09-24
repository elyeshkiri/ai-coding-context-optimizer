# ACCO — AI Coding Context Optimizer documentation

Use this page as the documentation map for the current ACCO release.

## Start here

- [Quickstart](QUICKSTART.md) — install, configure, verify, and run the first useful commands.
- [CLI reference](CLI_REFERENCE.md) — complete command index with per-command references.
- [Machine-readable CLI contracts](JSON_OUTPUTS.md) — stable JSON fields and exit/gating behavior.
- [Middleware SDKs](SDK.md) — embed ACCO in custom Python and TypeScript agents.
- [Worked end-to-end example](WORKED_EXAMPLE.md) — one real bug from setup through measured paired runs.
- [Configuration](CONFIGURATION.md) — project TOML, environment overrides, and host-managed files.
- [Troubleshooting](TROUBLESHOOTING.md) — setup, MCP, hooks, indexing, output recovery, and benchmark failures.
- [Upgrading](UPGRADING.md) — safe upgrade, repair, migration, and rollback workflow.

## Understand the system

- [Architecture](../ARCHITECTURE.md) — boundaries, dependency direction, ranking pipeline, MCP, hooks, and invariants.
- [Integrations](../INTEGRATIONS.md) — Claude Code, Cursor, Codex, OpenCode, OpenClaw, Hermes, Copilot, Antigravity, MCP, and host lifecycle.
- [Output optimization](../OUTPUT_OPTIMIZATION.md) — failure-aware compression, diagnostic Delta, and preservation rules.
- [Benchmarking](../BENCHMARKING.md) — deterministic retrieval evaluation and paired cost-per-success experiments.
- [Validation](../VALIDATION.md) — what has actually been run, frozen holdouts, and evidence limits.

## Contribute and operate

- [Contributing](../CONTRIBUTING.md) — development workflow, architecture rules, tests, and PR expectations.
- [Security & privacy](../SECURITY.md) — local data, managed files, secrets, output recovery, and disclosure guidance.
- [Changelog](../CHANGELOG.md) — release history.

## Recommended user journey

```text
pip install acco
        ↓
acco setup
        ↓
acco doctor
        ↓
acco browse / pack / MCP
        ↓
acco sessions / audit
        ↓
optional: optimize / provider-proxy / browser-context
        ↓
benchmark only when success is independently verifiable
```

The documentation deliberately separates **product usage** from **validation
claims**. A reduction in context size is not presented as an end-to-end cost
saving unless the task-success evidence supports that conclusion.

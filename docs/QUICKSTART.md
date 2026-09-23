# Quickstart

This guide gets **ACCO — AI Coding Context Optimizer** from installation to a verified local integration in
about five minutes.

## 1. Install

ACCO supports Python 3.10+.

```bash
python -m pip install --upgrade ai-coding-context-optimizer
```

The PyPI distribution is `ai-coding-context-optimizer`; the executable remains
`acco`.

Verify the executable and discover the complete command surface:

```bash
acco --help
acco commands
```

`--help` includes both registry-backed and legacy-compatible commands; you no
longer need README knowledge to discover `setup`, `doctor`, `pack`, or
`uninstall`.

## 2. Configure a project

From the repository you want your coding agent to work on:

```bash
cd /path/to/project
acco setup
```

Setup auto-detects supported hosts and configures only ACCO-owned entries.

Explicit host selection is also available:

```bash
acco setup . --host claude
acco setup . --host cursor --host codex
acco setup . --host opencode --host hermes
acco setup . --host copilot --host antigravity
acco setup . --host openclaw
acco setup . --host all
```

Setup is idempotent. `--host all` means all detected supported hosts, not every
product ACCO knows about. Re-running setup after an upgrade is the
supported repair/migration path.

## 3. Verify the installation

```bash
acco doctor .
```

A healthy report should show:

- the `acco` executable;
- a project `.acco.toml`;
- at least one configured supported host;
- a healthy repository index;
- Claude transcript evidence when Claude Code has already been used.

For automation:

```bash
acco doctor . --json
acco doctor . --require-ready
```

## 4. Try retrieval directly

Inspect ranked context without involving an agent:

```bash
acco browse . --query "refresh session token"
```

Build a bounded context pack:

```bash
acco pack . --query "refresh session token" --max-tokens 6000
```

Explain a surprising rank:

```bash
acco ranking-explain . --query "refresh session token"
```

## 5. Measure your existing context

```bash
acco audit .
acco sessions .
```

`audit` measures always-on project/user context. `sessions` reads Claude
Code transcripts and reports recorded API token fields plus estimated tool-result
sizes. These are measurements, not universal savings claims.

## 6. Optional project configuration

Setup creates a project-owned `.acco.toml`. A small excerpt of the
current defaults is:

```toml
version = 1

[hooks]
guard = true
read_max_lines = 220

[mcp]
profile = "full"
adaptive_max_tools = 12
compress_schemas = false

[provider]
prefix_tracking = true
```

The generated file contains additional output, routing, efficiency, ingress,
retrieval, and Smart Tool Proxy defaults. Setup does not overwrite an existing
project-owned config on upgrade; missing keys use runtime defaults until you add
them. Environment variables take precedence. See
[Configuration](CONFIGURATION.md) for the complete file and migration rules.

## 7. Recover or remove

Repair after changing host configuration:

```bash
acco setup .
acco doctor .
```

Remove ACCO-owned host entries:

```bash
acco uninstall . --host all
```

Also remove the project config:

```bash
acco uninstall . --host all --remove-config
```

Uninstall preserves unrelated MCP servers, unrelated Claude hooks, unmanaged
Codex configuration, and a user-modified generated Claude skill.

## Next

- [Worked end-to-end example](WORKED_EXAMPLE.md)
- [CLI reference](CLI_REFERENCE.md)
- [Machine-readable CLI contracts](JSON_OUTPUTS.md)
- [Integrations](../INTEGRATIONS.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Validation](../VALIDATION.md)

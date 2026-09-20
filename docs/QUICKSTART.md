# Quickstart

This guide gets Token Saver from installation to a verified local integration in
about five minutes.

## 1. Install

Token Saver supports Python 3.10+.

```bash
python -m pip install --upgrade claude-token-saver
```

The PyPI distribution is `claude-token-saver`; the executable remains
`token-saver`.

Verify the executable and discover the complete command surface:

```bash
token-saver --help
token-saver commands
```

`--help` includes both registry-backed and legacy-compatible commands; you no
longer need README knowledge to discover `setup`, `doctor`, `pack`, or
`uninstall`.

## 2. Configure a project

From the repository you want your coding agent to work on:

```bash
cd /path/to/project
token-saver setup
```

Setup auto-detects supported hosts and configures only Token Saver-owned entries.

Explicit host selection is also available:

```bash
token-saver setup . --host claude
token-saver setup . --host cursor --host codex
token-saver setup . --host all
```

Setup is idempotent. Re-running it after an upgrade is the supported
repair/migration path.

## 3. Verify the installation

```bash
token-saver doctor .
```

A healthy report should show:

- the `token-saver` executable;
- a project `.token-saver.toml`;
- at least one configured supported host;
- a healthy repository index;
- Claude transcript evidence when Claude Code has already been used.

For automation:

```bash
token-saver doctor . --json
token-saver doctor . --require-ready
```

## 4. Try retrieval directly

Inspect ranked context without involving an agent:

```bash
token-saver browse . --query "refresh session token"
```

Build a bounded context pack:

```bash
token-saver pack . --query "refresh session token" --max-tokens 6000
```

Explain a surprising rank:

```bash
token-saver ranking-explain . --query "refresh session token"
```

## 5. Measure your existing context

```bash
token-saver audit .
token-saver sessions .
```

`audit` measures always-on project/user context. `sessions` reads Claude
Code transcripts and reports recorded API token fields plus estimated tool-result
sizes. These are measurements, not universal savings claims.

## 6. Optional project configuration

Setup creates:

```toml
version = 1

[hooks]
guard = true
read_max_lines = 220
reread = false
delta = false
min_lines = 40
keep_tail = 15
allow = []
```

Environment variables override the project file. See
[Configuration](CONFIGURATION.md) for the full precedence and migration rules.

## 7. Recover or remove

Repair after changing host configuration:

```bash
token-saver setup .
token-saver doctor .
```

Remove Token Saver-owned host entries:

```bash
token-saver uninstall . --host all
```

Also remove the project config:

```bash
token-saver uninstall . --host all --remove-config
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

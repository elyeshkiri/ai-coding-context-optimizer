# Upgrading and migration

Token Saver treats setup as an idempotent repair/migration operation.

## Standard upgrade

```bash
python -m pip install --upgrade claude-token-saver
cd /path/to/project
token-saver setup .
token-saver doctor .
```

This refreshes Token Saver-owned host entries without duplicating them.

## Why rerun setup?

New releases can change:

- Claude hook matchers/events (including the `Stop`/`StopFailure` hooks used
  for output-budget telemetry);
- MCP command arguments;
- generated project defaults;
- managed Codex block contents;
- generated on-demand skills.

Setup re-applies the current managed representation while preserving unrelated
configuration.

## Project configuration upgrades

`.token-saver.toml` is user/project-owned after creation. Setup does not replace
an existing file.

When a release adds new optional keys, existing projects continue to use code
defaults until you add those keys. Output telemetry therefore defaults to
enabled even for an older config that does not yet contain `telemetry = true`;
set `output.telemetry = false` or `TOKEN_SAVER_OUTPUT_TELEMETRY=0` to opt out.

Environment variables remain higher-priority overrides.

## From manual integrations to managed setup

If Claude/Cursor already has a normal `mcpServers.token-saver` entry, setup can
refresh that owned key.

Codex is stricter: an unmanaged `[mcp_servers.token-saver]` section is not
silently converted. Remove or rename it yourself before using managed setup.

## Legacy `token-saver install`

The lower-level Claude-only installer remains supported for compatibility.

New projects should prefer:

```bash
token-saver setup . --host claude
```

because setup configures both hooks and MCP and participates in the unified
doctor/uninstall lifecycle.

## Rollback

1. Install the desired older package version.
2. Re-run that version's setup/install command.
3. Run the matching doctor/host checks.
4. Do not reuse a newer benchmark claim as evidence for an older binary.

Example:

```bash
python -m pip install "claude-token-saver==1.4.0"
```

If that version predates unified setup, follow its release documentation and
use the legacy installer where required.

## Remove managed integration before a clean reinstall

```bash
token-saver uninstall . --host all
python -m pip install --force-reinstall claude-token-saver
token-saver setup .
token-saver doctor .
```

Add `--remove-config` only if you also want to delete
`.token-saver.toml`.

## Release provenance

Project versions are immutable. The release workflow refuses to reuse an
existing version tag for a different commit, builds/validates distributions
before publication, and creates the GitHub release only after PyPI publication
succeeds.

See [CHANGELOG.md](../CHANGELOG.md) for version-specific behavior.

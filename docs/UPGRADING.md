# Upgrading and migration

Token Saver treats setup as an idempotent repair/migration operation.

## 1.8 frozen session-efficiency holdout

Version 1.8 adds benchmark/evaluation commands and a paid workflow; it does not
change the default 1.7 runtime session-efficiency switches.

New commands:

- `token-saver session-holdout` — run/resume the two-phase frozen experiment,
  blind grading, and effectiveness report;
- `token-saver session-holdout-evaluate` — evaluate already merged evidence
  without rerunning agents.

The new frozen manifest reuses the existing 24 SWE-bench Verified task cohort
but changes the runner protocol, so it has its own independent task-definition
hash. Do not edit that manifest in place and continue calling the result the
same holdout.

The control label `v1.6-session-baseline` means **1.6 session behavior emulated
by the current binary with session efficiency disabled**. It is intentionally
not a historical package checkout.

## 1.7 session-efficiency control plane

Version 1.7 widens Claude `PostToolUse` from `Bash|Read` to
`Bash|Read|Edit|Write` so structured continuity can observe edits without
rewriting their tool result. Rerun `token-saver setup` after upgrading so the
managed project hook matcher is refreshed.

A new `[efficiency]` config table defaults on for continuity, exact cross-turn
dedup, and bounded waste detection. Existing configs without the table keep
working and receive the safe defaults. Use the documented
`TOKEN_SAVER_EFFICIENCY`, `TOKEN_SAVER_CONTINUITY`,
`TOKEN_SAVER_CROSS_TURN_DEDUP`, or `TOKEN_SAVER_WASTE_DETECTION` overrides
for temporary rollback.

The new efficiency snapshot/event files live under the existing private Token
Saver state directory. They do not alter repository files, ranking indexes, or
frozen benchmark definitions.

## 1.6 evidence pipeline

Version 1.6 adds `blind-grade` and `evidence-run`, plus cache-TTL-aware
experiment telemetry. Existing project integrations should rerun setup so the
managed Claude hooks stay current. Historical experiment files remain readable;
new publishable output-cost evidence should use the full frozen/graded pipeline.

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

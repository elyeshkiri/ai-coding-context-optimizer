# Troubleshooting

Start with:

```bash
token-saver doctor .
```

Then use the symptom-specific checks below.

## `token-saver` is not found

Check the Python environment:

```bash
python -m pip show claude-token-saver
python -m pip install --upgrade claude-token-saver
python -m pip --version
```

If installation succeeded but the executable is missing, verify that the Python
environment's scripts/bin directory is on `PATH`.

## A host is detected but not configured

Repair managed entries:

```bash
token-saver setup .
token-saver doctor .
```

Or target one host:

```bash
token-saver setup . --host claude
```

## Setup refuses invalid JSON

Token Saver intentionally does not overwrite malformed host configuration.

Fix the JSON file named in the error, then rerun setup. For multi-host setup,
preflight happens before writes, so earlier hosts should not have been partially
modified.

## Setup refuses Codex configuration

If the error mentions an unmanaged Token Saver Codex section, inspect
`~/.codex/config.toml`.

Token Saver only owns sections surrounded by its managed markers. It refuses to
replace a pre-existing unmanaged `[mcp_servers.token-saver]` block.

Either remove/rename that manual section yourself or keep managing Codex
manually.

## Claude hooks are configured but not behaving as expected

Run:

```bash
token-saver host-check . --host claude
```

For host-level proof of `updatedToolOutput` acceptance, supply live/debug
evidence using the flags documented by:

```bash
token-saver host-check --help
```

Remember that `doctor` verifies configuration health; `host-check` is the
deeper transport/live-evidence diagnostic.

## MCP server does not start

Test the server directly:

```bash
token-saver serve /absolute/path/to/project
```

Then verify the managed host config with:

```bash
token-saver doctor . --json
```

Project-scoped Claude/Cursor MCP entries use an absolute project path to avoid
working-directory ambiguity.

## Repository index looks stale

A long-running MCP server can explicitly refresh:

```text
refresh_index
```

From the CLI, rerun the repository-aware command; a fresh
`RepositoryContextService` rebuilds/loads its index according to the normal
persistence policy.

For structural maps:

```bash
token-saver map . --check-stale
token-saver map . --refresh-if-stale
```

## A large source read is unexpectedly blocked

Inspect the active config:

```bash
token-saver doctor . --json
```

Adjust `.token-saver.toml`:

```toml
[hooks]
read_max_lines = 400
allow = ["generated/*"]
```

Or temporarily disable the guard:

```bash
TOKEN_SAVER_GUARD=0 claude
```

Prefer bounded line-range reads instead of globally disabling protection.

## Command output was compressed and I need the original

The hook stores the original result when replacement is beneficial.

The replacement message includes an id. Recover it with:

```bash
token-saver output <id> --stream stdout --offset 1 --limit 80
```

Delete old stored results:

```bash
token-saver outputs-prune --days 7
```

## Diagnostic Delta is not activating

Delta is opt-in:

```bash
TOKEN_SAVER_DELTA=1 claude
```

or:

```toml
[hooks]
delta = true
```

It only replaces output when the supported diagnostic comparison is valid and
the rendered delta is smaller than the normal compressed output.

## Ranking moved after a PR

Use the PR ranking-regression artifact or reproduce locally:

```bash
token-saver ranking-snapshot benchmarks/context-quality.json --path . --out snapshot.json
token-saver ranking-explain . --query "the task"
```

`ranking-diff` reports expected-file movement and per-stage score changes.
The repository's historical calibration remains descriptive until its configured
minimum independent-PR evidence floor is reached.

## Benchmark says evidence is not publishable

That is expected when protocol requirements are not met.

Broad cost-per-success publication requires the constraints documented in
[BENCHMARKING.md](../BENCHMARKING.md), including frozen task definitions,
independent verification, enough distinct tasks/trials, one exact model id, and
randomized condition order.

Do not bypass the gate to create a headline number.

## Uninstall left a Claude skill file

If `.claude/skills/token-budget/SKILL.md` was modified after setup, Token Saver
intentionally preserves it. Remove it manually if the modifications are yours
and the file is no longer wanted.

## Still stuck

Collect:

```bash
token-saver doctor . --json
token-saver commands
python --version
python -m pip show claude-token-saver
```

When reporting a bug, include the failing command, exit code, traceback/error
text, OS/Python version, and a minimal configuration sample with secrets removed.

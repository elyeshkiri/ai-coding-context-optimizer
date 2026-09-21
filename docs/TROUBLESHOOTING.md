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

The replacement can include both the legacy paged-output id and a universal
`tsr_...` recovery handle. Use either path:

```bash
token-saver output <id> --stream stdout --offset 1 --limit 80
token-saver recover tsr_... --path .
```

Delete old stored results:

```bash
token-saver outputs-prune --days 7
```

## A `tsr_...` recovery handle cannot be resolved

Recovery handles are project-scoped. Use the same project root that produced the
compressed representation:

```bash
token-saver recover tsr_... --path .
token-saver recovery-status . --json
```

If the handle is unknown under that project, verify `TOKEN_SAVER_STATE_DIR`
and the project path. Handles are identifiers, not remote object URLs; Token
Saver does not fetch missing recovery payloads from a service.

If a transform reports that recovery capacity is exhausted, inspect
`recovery-status`. Token Saver intentionally refuses the new lossy transform
rather than evicting an older source record and creating a dangling handle.

For Bash output, the legacy paged-output id remains usable:

```bash
token-saver output <id> --stream stdout --offset 1 --limit 80
```

## Adaptive MCP is missing a tool I expected

Adaptive mode starts with a small core and expands after `discover_tools`.
Inspect the configured profile first:

```bash
token-saver doctor . --json
```

Use `mcp.profile = "full"` as the compatibility fallback when a host does not
honor MCP `listChanged` notifications or cannot refresh the tool list. Schema
compression is independent: set `mcp.compress_schemas = false` when diagnosing
a host that rejects compressed descriptions/annotations.

Exact `recover_context` stays in the adaptive core so a model-visible
`tsr_...` handle always has a recovery path.

## Provider proxy refuses to start or returns an upstream error

Validate the explicit trust boundary:

```bash
token-saver provider-proxy . \
  --provider anthropic \
  --upstream https://api.anthropic.com
```

The proxy rejects non-loopback binding unless `--allow-non-loopback` is
explicitly supplied. Plain HTTP upstreams are accepted only for localhost.
Credentials must be supplied by the client headers, not embedded in the
upstream URL.

Automatic redirect following is disabled. A provider redirect is returned to
the client instead of silently forwarding authorization headers to another
origin. A `502` means the configured upstream could not be reached; Token
Saver does not silently switch providers.

Use `token-saver prefix-status .` to inspect content-free stable-prefix reuse
evidence. Disable only that telemetry with `--no-prefix-tracking` when testing
request transformation behavior.

## `token-saver optimize` will not keep or revert a change yet

The optimizer requires enough **provider-reported** measured turns in both the
baseline and treatment windows. Inspect the journal:

```bash
token-saver optimize . --status --json
token-saver optimize . --evaluate opt_... --json
```

`insufficient-baseline` or `insufficient-treatment` means the evidence floor
has not been met; it is not treated as zero savings. By default, a completed
comparison that fails the configured improvement threshold restores the exact
pre-change Token Saver config from recovery.

The optimizer edits only Token Saver-owned project configuration. It does not
rewrite application source or arbitrary host/provider settings.

## Browser context was not compressed

`browser-context` accepts captured HTML or AX-like text; it does not fetch a
URL. A transform is returned only when the focused representation plus recovery
handle is actually smaller than the original.

```bash
token-saver browser-context page.html --query "checkout total" --json
```

If `changed` is false, the original was kept because focusing did not reduce
estimated context or exact recovery could not be guaranteed.

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

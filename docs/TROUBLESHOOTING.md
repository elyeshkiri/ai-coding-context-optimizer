# Troubleshooting

Start with:

```bash
acco doctor .
```

Then use the symptom-specific checks below.

## `acco` is not found

Check the Python environment:

```bash
python -m pip show ai-coding-context-optimizer
python -m pip install --upgrade ai-coding-context-optimizer
python -m pip --version
```

If installation succeeded but the executable is missing, verify that the Python
environment's scripts/bin directory is on `PATH`.

## A host is detected but not configured

Repair managed entries:

```bash
acco setup .
acco doctor .
```

Or target one host:

```bash
acco setup . --host claude
```

## Setup refuses invalid JSON

ACCO intentionally does not overwrite malformed host configuration.

Fix the JSON file named in the error, then rerun setup. For multi-host setup,
preflight happens before writes, so earlier hosts should not have been partially
modified.

## Setup refuses Codex configuration

If the error mentions an unmanaged ACCO Codex section, inspect
`~/.codex/config.toml`.

ACCO only owns sections surrounded by its managed markers. It refuses to
replace a pre-existing unmanaged `[mcp_servers.acco]` block.

Either remove/rename that manual section yourself or keep managing Codex
manually.

## Setup refuses OpenCode configuration

ACCO manages OpenCode through project `.opencode/opencode.json`.
If only `.opencode/opencode.jsonc` already exists, setup fails closed instead
of creating a second project config with ambiguous precedence.

Either add the ACCO MCP entry to the existing JSONC file manually or
choose one project config representation before rerunning setup.

## Setup refuses Hermes configuration

Hermes uses the top-level `mcp_servers` mapping in
`~/.hermes/config.yaml`. ACCO owns only its marked block and refuses:

- an unmanaged same-name `acco` entry;
- duplicate top-level `mcp_servers` keys;
- inline/complex `mcp_servers` shapes that cannot be safely edited.

Preserve the existing configuration and normalize it manually before rerunning
`acco setup . --host hermes`.

## OpenClaw setup or uninstall fails

OpenClaw is configured through its native registry rather than by editing its
JSON5 file directly:

```bash
openclaw mcp
acco setup . --host openclaw
```

The `openclaw` executable must be available on `PATH` for managed setup or
removal. ACCO respects `OPENCLAW_CONFIG_PATH` when locating the active
registry for detection.

## Copilot setup is not detected

ACCO supports both Copilot CLI and the VS Code Copilot MCP surface.

For Copilot CLI, verify:

```bash
copilot --version
copilot mcp
acco setup . --host copilot
```

For VS Code, ACCO recognizes an installed GitHub Copilot extension or an
existing workspace `.vscode/mcp.json`. A generic VS Code installation alone is
not treated as Copilot.

If the Copilot CLI already has a user-owned MCP server named `acco`,
ACCO refuses to replace it. Rename/remove that manual entry before using
managed setup.

## Antigravity is not detected

Current Antigravity CLI detection uses the `agy` executable. Workspace MCP is
stored in `.agents/mcp_config.json`; the documented global MCP profile is also
reported by doctor when present.

Run:

```bash
agy --help
acco setup . --host antigravity
acco doctor . --json
```

## Claude hooks are configured but not behaving as expected

Run:

```bash
acco host-check . --host claude
```

For host-level proof of `updatedToolOutput` acceptance, supply live/debug
evidence using the flags documented by:

```bash
acco host-check --help
```

Remember that `doctor` verifies configuration health; `host-check` is the
deeper transport/live-evidence diagnostic.

## MCP server does not start

Test the server directly:

```bash
acco serve /absolute/path/to/project
```

Then verify the managed host config with:

```bash
acco doctor . --json
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
acco map . --check-stale
acco map . --refresh-if-stale
```

## A large source read is unexpectedly blocked

Inspect the active config:

```bash
acco doctor . --json
```

Adjust `.acco.toml`:

```toml
[hooks]
read_max_lines = 400
allow = ["generated/*"]
```

Or temporarily disable the guard:

```bash
ACCO_GUARD=0 claude
```

Prefer bounded line-range reads instead of globally disabling protection.

## Command output was compressed and I need the original

The hook stores the original result when replacement is beneficial.

The replacement can include both the legacy paged-output id and a universal
`tsr_...` recovery handle. Use either path:

```bash
acco output <id> --stream stdout --offset 1 --limit 80
acco recover tsr_... --path .
```

Delete old stored results:

```bash
acco outputs-prune --days 7
```

## A `tsr_...` recovery handle cannot be resolved

Recovery handles are project-scoped. Use the same project root that produced the
compressed representation:

```bash
acco recover tsr_... --path .
acco recovery-status . --json
```

If the handle is unknown under that project, verify `ACCO_STATE_DIR`
and the project path. Handles are identifiers, not remote object URLs; Token
Saver does not fetch missing recovery payloads from a service.

If a transform reports that recovery capacity is exhausted, inspect
`recovery-status`. ACCO intentionally refuses the new lossy transform
rather than evicting an older source record and creating a dangling handle.

For Bash output, the legacy paged-output id remains usable:

```bash
acco output <id> --stream stdout --offset 1 --limit 80
```

## Adaptive MCP is missing a tool I expected

Adaptive mode starts with a small core and expands after `discover_tools`.
Inspect the configured profile first:

```bash
acco doctor . --json
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
acco provider-proxy . \
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

Use `acco prefix-status .` to inspect content-free stable-prefix reuse
evidence. Disable only that telemetry with `--no-prefix-tracking` when testing
request transformation behavior.

## `acco optimize` will not keep or revert a change yet

The optimizer requires enough **provider-reported** measured turns in both the
baseline and treatment windows. Inspect the journal:

```bash
acco optimize . --status --json
acco optimize . --evaluate opt_... --json
```

`insufficient-baseline` or `insufficient-treatment` means the evidence floor
has not been met; it is not treated as zero savings. By default, a completed
comparison that fails the configured improvement threshold restores the exact
pre-change ACCO config from recovery.

The optimizer edits only ACCO-owned project configuration. It does not
rewrite application source or arbitrary host/provider settings.

## Browser context was not compressed

`browser-context` accepts captured HTML or AX-like text; it does not fetch a
URL. A transform is returned only when the focused representation plus recovery
handle is actually smaller than the original.

```bash
acco browser-context page.html --query "checkout total" --json
```

If `changed` is false, the original was kept because focusing did not reduce
estimated context or exact recovery could not be guaranteed.

## Diagnostic Delta is not activating

Delta is opt-in:

```bash
ACCO_DELTA=1 claude
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
acco ranking-snapshot benchmarks/context-quality.json --path . --out snapshot.json
acco ranking-explain . --query "the task"
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

If `.claude/skills/token-budget/SKILL.md` was modified after setup, ACCO
intentionally preserves it. Remove it manually if the modifications are yours
and the file is no longer wanted.

## Still stuck

Collect:

```bash
acco doctor . --json
acco commands
python --version
python -m pip show ai-coding-context-optimizer
```

When reporting a bug, include the failing command, exit code, traceback/error
text, OS/Python version, and a minimal configuration sample with secrets removed.

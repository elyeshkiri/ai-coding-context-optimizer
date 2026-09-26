# `acco wrap`

Launch a coding-agent process through an ephemeral loopback ACCO provider proxy.

## Synopsis

```bash
acco wrap [wrapper-options] AGENT [-- AGENT_ARGS...]
```

Examples:

```bash
acco wrap claude
acco wrap codex -- --help
acco wrap --model-routing calibrated claude
acco wrap --dry-run --json claude
```

## Arguments and options

- `AGENT` — preset agent name (`claude`, `codex`, or `gemini`) or a custom executable name.
- `AGENT_ARGS` — remaining arguments forwarded unchanged to the child.
- `--path` — working/project root; defaults to `.`.
- `--bind` / `--port` — local proxy listener; port `0` chooses an ephemeral port.
- `--provider`, `--upstream`, `--base-url-env` — required together for unknown agents.
- `--executable` — override the child executable name/path lookup.
- `--model-routing off|observe|calibrated` — provider routing mode; defaults to `off`.
- `--dry-run` — print the launch plan without starting the proxy or agent.
- `--json` — with `--dry-run`, emit the plan as JSON.

Presets use `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` (with the local `/v1`
path), or `GOOGLE_GEMINI_BASE_URL`. Credentials remain in the inherited child
environment and are not copied into files.

## Exit codes

- In live mode, returns the child agent's exit code.
- `0` — successful dry-run.
- `2` — invalid wrapper configuration, missing executable, or proxy startup failure.

## Output contract

Dry-run JSON contains the agent, executable, provider, upstream, base-URL
environment key, local base URL, forwarded argv, and routing mode. Live mode
does not rewrite child stdout/stderr; it owns only the ephemeral proxy lifecycle
and child environment override.

## Authoritative runtime help

Run `acco wrap --help` for wrapper flags. Agent-specific flags after `--` are
defined by the selected agent.

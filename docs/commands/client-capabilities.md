# `token-saver client-capabilities`

Inspect Token Saver's conservative capability contract for supported agent hosts.

## Synopsis

```bash
token-saver client-capabilities [--client CLIENT] [--json]
```

## Arguments and options

- `--client CLIENT` — show one host in detail. Accepted canonical names include `claude-code`, `codex`, `cursor`, `gemini-cli`, and `generic-mcp`; common aliases are normalized.
- `--json` — emit the machine-readable registry or selected-client report.

Capabilities are intentionally conservative. `yes` means Token Saver may rely on the
boundary without fallback; `conditional` and `advisory` remain non-guaranteed;
`unknown` is never treated as support.

## Exit codes

- `0` — capability report produced successfully.
- `2` — argparse usage error.

## Output contract

Per-client JSON contains a `client` record and feature-level `features` evidence.
Each feature reports exact prerequisite capability levels, whether support is
`guaranteed`, and whether a compatibility fallback remains available.

See [Machine-readable contracts](../JSON_OUTPUTS.md#client-capabilities---json).

## Authoritative runtime help

Run `token-saver client-capabilities --help` for the installed version.

# `acco update`

Inspect or apply the recommended package-manager upgrade for ACCO.

## Synopsis

```bash
acco update [--apply] [--json]
```

## Arguments and options

- `--apply` — execute the detected upgrade command.
- `--json` — emit package-manager, command, apply state, and return code.

ACCO prefers `uv tool upgrade acco` when `uv` is available, then
`pipx upgrade acco`, and otherwise falls back to the current Python
interpreter's `pip install --upgrade acco`.

No package-manager mutation occurs unless `--apply` is explicit.

## Exit codes

Without `--apply`, returns `0`. With `--apply`, returns the selected package
manager's exit code.

## Output contract

JSON fields are `schema`, `manager`, `command`, `applied`, and
`returncode`. The command does not edit project configuration; rerun
`acco setup` after an upgrade to repair/migrate integrations idempotently.

## Authoritative runtime help

Run `acco update --help` for the installed version.

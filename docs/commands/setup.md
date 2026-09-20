# `token-saver setup`

Auto-detect/configure supported coding-agent integrations.

## Synopsis

```bash
token-saver setup [path] [--host claude|cursor|codex|all ...] [--json]
```

## Arguments and options

- `path` default `.`.
- `--host` repeatable; omitted means auto-detect.
- `--json` emits lifecycle result.

## Exit codes

`0` success; `2` invalid/conflicting host config or unsafe mutation refused.

## Output contract

Human setup summary or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#setup-json).

## Authoritative runtime help

Run `token-saver setup --help` for argparse's exact usage text for the installed version.

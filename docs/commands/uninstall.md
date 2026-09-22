# `token-saver uninstall`

Remove only Token Saver-owned host integration entries.

## Synopsis

```bash
token-saver uninstall [path] [--host HOST|all ...] [--remove-config] [--json]
```

## Arguments and options

- `path` default `.`.
- `--host` repeatable; default is all supported hosts: `claude`, `cursor`, `codex`, `opencode`, `openclaw`, `hermes`, `copilot`, and `antigravity`.
- `--remove-config` also removes `.token-saver.toml`.
- `--json` emits lifecycle result.

## Exit codes

`0` success; `2` invalid/conflicting managed config.

## Output contract

Human removal summary or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#uninstall-json).

## Authoritative runtime help

Run `token-saver uninstall --help` for argparse's exact usage text for the installed version.

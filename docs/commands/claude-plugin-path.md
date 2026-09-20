# `token-saver claude-plugin-path`

Render the complete Token Saver Claude Code plugin directory and print its absolute path.

## Synopsis

```bash
token-saver claude-plugin-path
token-saver claude-plugin-path --json
```

This command is also the stable bridge used by the Claude marketplace command-source entry.

## Arguments and options

- `--json` — emit version, path, schema, and rendered status.

The generated plugin contains Token Saver-owned hooks, MCP configuration, and the staged-prompt resume skill. Hook/MCP commands invoke `python -m token_saver.entry`, so the generated plugin does not require the `token-saver` console script to be on `PATH`.

## Exit codes

- `0` — plugin rendered successfully.
- `2` — local plugin directory could not be created.

## Output contract

Text mode prints one absolute plugin directory path and nothing else, which is suitable for Claude Code command-source marketplace installation. JSON mode emits `schema`, `version`, `path`, and `rendered`.

## Authoritative runtime help

```bash
token-saver claude-plugin-path --help
```

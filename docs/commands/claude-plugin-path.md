# `acco claude-plugin-path`

Render the complete ACCO Claude Code plugin directory and print its absolute path.

## Synopsis

```bash
acco claude-plugin-path
acco claude-plugin-path --json
```

This command is also the stable bridge used by the Claude marketplace command-source entry.

## Arguments and options

- `--json` — emit version, path, schema, and rendered status.

The generated plugin contains ACCO-owned hooks, MCP configuration, and the staged-prompt resume skill. Hook/MCP commands invoke `python -m acco.entry`, so the generated plugin does not require the `acco` console script to be on `PATH`.

## Exit codes

- `0` — plugin rendered successfully.
- `2` — local plugin directory could not be created.

## Output contract

Text mode prints one absolute plugin directory path and nothing else, which is suitable for Claude Code command-source marketplace installation. JSON mode emits `schema`, `version`, `path`, and `rendered`.

## Authoritative runtime help

```bash
acco claude-plugin-path --help
```

# `acco continuity`

Inspect the latest structured local working-state checkpoint.

## Synopsis

```bash
acco continuity [path] [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--json` — print the stable machine-readable checkpoint.

The checkpoint contains task class, bounded working-file paths, redacted recent
command labels, validation status, and recent failures. It deliberately does not
store raw user prompts, assistant responses, or tool output.

Claude Code can consume the same compact checkpoint automatically on
`SessionStart` resume/compact events.

## Exit codes

`0` inspection completed, including when no checkpoint exists.

## Output contract

See [Machine-readable contracts](../JSON_OUTPUTS.md#continuity---json).

## Authoritative runtime help

Run `acco continuity --help` for the installed version.

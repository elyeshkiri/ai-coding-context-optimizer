# `token-saver map`

Build a compact structural repository map.

## Synopsis

```bash
token-saver map [path] [-o FILE] [--max-tokens N] [--docstrings] [--no-gitignore] [--check-stale] [--refresh-if-stale]
```

## Arguments and options

- `path` default `.`.
- `-o/--out` writes a file.
- `--max-tokens` hard-caps the map.
- `--docstrings` keeps first Python docstring lines.
- `--no-gitignore` includes ignored files.
- `--check-stale` checks freshness.
- `--refresh-if-stale` refreshes the map when needed.

## Exit codes

`0` success; `1` invalid path/map operation failure.

## Output contract

Map text or write-status output.

## Authoritative runtime help

Run `token-saver map --help` for argparse's exact usage text for the installed version.

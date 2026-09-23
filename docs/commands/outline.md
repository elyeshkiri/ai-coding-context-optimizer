# `acco outline`

Render signatures/structure instead of a whole source file.

## Synopsis

```bash
acco outline <file> [--docstrings] [-q|--quiet] [--no-line-numbers]
```

## Arguments and options

- `file` required.
- `--docstrings` keeps first Python docstring lines.
- `-q/--quiet` suppresses savings note.
- `--no-line-numbers` removes the range gutter.

## Exit codes

`0` success; `1` missing/invalid file.

## Output contract

Outline on stdout; savings note on stderr unless quiet.

## Authoritative runtime help

Run `acco outline --help` for argparse's exact usage text for the installed version.

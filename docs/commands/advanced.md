# `acco advanced`

List ACCO's complete expert command surface without crowding the beginner home screen.

## Synopsis

```bash
acco advanced
```

## Arguments and options

No arguments or options are required. Use the listed command's own `--help`
for its detailed interface.

## Exit codes

Returns `0` after listing commands; invalid arguments return argparse's
standard nonzero usage exit.

## Output contract

Prints the registered and legacy-compatible advanced commands in deterministic
order. Beginner commands such as `setup`, `start`, `status`, `demo`,
`savings`, `update`, and `uninstall` are intentionally omitted from this
expert list.

## Authoritative runtime help

Run `acco advanced --help` for the installed version.

# `token-saver install`

Legacy/low-level Claude hook installer; prefer `setup`.

## Synopsis

```bash
token-saver install [path] [--user] [--templates]
```

## Arguments and options

- `path` default `.`.
- `--user` writes user Claude settings instead of project settings.
- `--templates` installs generated Token Saver skill templates.

## Exit codes

`0` success.

## Output contract

Path/status text. New installations should use [`setup`](setup.md).

## Authoritative runtime help

Run `token-saver install --help` for argparse's exact usage text for the installed version.

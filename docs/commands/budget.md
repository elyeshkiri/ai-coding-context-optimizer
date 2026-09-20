# `token-saver budget`

Compare measured project context with recommended window slices.

## Synopsis

```bash
token-saver budget [path] [--window N] [--no-user-scope] [--exact] [--model MODEL]
```

## Arguments and options

- `path` default `.`.
- `--window` default `200000`.
- `--no-user-scope` excludes user Claude config.
- `--exact` enables provider token counting.
- `--model` selects the exact-counting model.

## Exit codes

`0` success; `1` invalid window or audit failure.

## Output contract

Human-readable budget table.

## Authoritative runtime help

Run `token-saver budget --help` for argparse's exact usage text for the installed version.

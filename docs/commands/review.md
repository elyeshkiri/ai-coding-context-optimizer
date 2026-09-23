# `acco review`

Review a Git diff using bounded repository evidence.

## Synopsis

```bash
acco review [path] [--base REV] [--staged] [--json] [--max-tokens N]
```

## Arguments and options

- Shared patch flags: path default `.`, base default `HEAD`, `--staged`, `--json`, max tokens default `6000`.

## Exit codes

`0` success; `2` invalid patch/repository request.

## Output contract

Human file/warning report or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#review-json).

## Authoritative runtime help

Run `acco review --help` for argparse's exact usage text for the installed version.

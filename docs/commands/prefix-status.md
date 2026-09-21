# `token-saver prefix-status`

Inspect content-free stable provider-prefix reuse evidence.

## Synopsis

```bash
token-saver prefix-status [path] [--json]
```

## Arguments and options

- `path` — project root; default current directory.
- `--json` — emit per-provider counters and fingerprints.

## Exit codes

`0` report generated.

## Output contract

Reports prefix fingerprints, estimated stable-prefix size, hit/miss counts, and
reuse rate. Provider request text is not persisted by this feature.

## Authoritative runtime help

Run `token-saver prefix-status --help` for the installed version.

# `token-saver evaluate`

Evaluate retrieval against a manifest or compute its freeze hash.

## Synopsis

```bash
token-saver evaluate <manifest> [--path PATH] [--max-tokens N] [--require-holdout] [--print-ground-truth-hash]
```

## Arguments and options

- `manifest` required.
- `--path` default `.`.
- `--max-tokens` default `6000`.
- `--require-holdout` enforces frozen/development-excluded protocol metadata and pinned revisions.
- `--print-ground-truth-hash` hashes the ground-truth definition without retrieval.

## Exit codes

`0` success; `2` malformed manifest/protocol/repository mismatch.

## Output contract

Evaluation is always JSON except hash-only mode; see [Machine-readable contracts](../JSON_OUTPUTS.md#evaluate-always-json).

## Authoritative runtime help

Run `token-saver evaluate --help` for argparse's exact usage text for the installed version.

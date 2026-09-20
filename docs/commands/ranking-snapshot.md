# `token-saver ranking-snapshot`

Capture trace-enabled ranking evidence for a frozen/evaluation manifest.

## Synopsis

```bash
token-saver ranking-snapshot <manifest> [--path PATH] [--max-files N] [--graph-hops N] [--closure-items N] [--embeddings] [--out FILE]
```

## Arguments and options

- `manifest` required.
- `--path` default `.`.
- `--max-files` default `20`.
- `--graph-hops` default `1`.
- `--closure-items` default `20`.
- `--embeddings` enables local embedding rerank.
- `--out` writes JSON instead of stdout.

## Exit codes

`0` success; `2` manifest/revision/output failure.

## Output contract

Always JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#ranking-snapshot-always-json-or---out).

## Authoritative runtime help

Run `token-saver ranking-snapshot --help` for argparse's exact usage text for the installed version.

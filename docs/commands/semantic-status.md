# `token-saver semantic-status`

Inspect Token Saver's persistent local semantic-vector index without loading the embedding model.

## Synopsis

```bash
token-saver semantic-status [path]
token-saver semantic-status [path] --json
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--json` — emit machine-readable status.

This command is safe to use even when the optional embedding dependencies are not installed.

## Exit codes

- `0` — status reported successfully.

## Output contract

Reports `schema`, synchronized file count, chunk count, vector dimensions, model identity, backend (`hnsw` or `sqlite-cosine`), and the private local index path.

## Authoritative runtime help

```bash
token-saver semantic-status --help
```

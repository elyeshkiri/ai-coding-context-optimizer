# `token-saver semantic-index`

Build or incrementally refresh Token Saver's persistent local chunk-level semantic index.

## Synopsis

```bash
token-saver semantic-index [path]
token-saver semantic-index [path] --json
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--json` — emit machine-readable index status.

The command requires the local embedding dependency and an already-downloaded `all-MiniLM-L6-v2` model. Install the optional exact-scan semantic dependency with `pip install 'claude-token-saver[embeddings]'`. Install `hnswlib` through `pip install 'claude-token-saver[semantic-ann]'` to persist an HNSW sidecar; otherwise Token Saver uses exact cosine scan over the same persistent vectors.

Only vectors and source coordinates are stored. Source text is not duplicated into the semantic database.

## Exit codes

- `0` — index synchronized successfully.
- `2` — embedding dependency/model unavailable, repository I/O failure, or invalid semantic state.

## Output contract

Text mode prints file count, chunk count, embedding dimensions, active backend, and private local index path. JSON mode emits `schema`, `files`, `chunks`, `dimensions`, `model`, `backend`, and `path`.

## Authoritative runtime help

```bash
token-saver semantic-index --help
```

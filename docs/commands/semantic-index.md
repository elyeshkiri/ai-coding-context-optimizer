# `acco semantic-index`

Build or incrementally refresh ACCO's persistent local chunk-level semantic index.

## Synopsis

```bash
acco semantic-index [path]
acco semantic-index [path] --json
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--json` — emit machine-readable index status.

The command requires an already-downloaded `all-MiniLM-L6-v2` model. `pip install 'ai-coding-context-optimizer[semantic]'` installs both SentenceTransformers and optional HNSW acceleration. The backward-compatible `[embeddings]` extra installs only SentenceTransformers and uses exact cosine scan; `[semantic-ann]` can add HNSW separately.

Only vectors and source coordinates are stored. Source text is not duplicated into the semantic database.

## Exit codes

- `0` — index synchronized successfully.
- `2` — embedding dependency/model unavailable, repository I/O failure, or invalid semantic state.

## Output contract

Text mode prints file count, chunk count, embedding dimensions, active backend, and private local index path. JSON mode emits `schema`, `files`, `chunks`, `dimensions`, `model`, `backend`, and `path`.

## Authoritative runtime help

```bash
acco semantic-index --help
```

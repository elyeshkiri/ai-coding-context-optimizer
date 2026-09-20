# `token-saver recall`

Retrieve durable project findings relevant to the current task without re-reading or re-deriving every conclusion.

## Synopsis

```bash
token-saver recall [path] --query "debug session refresh"
token-saver recall [path] --query "debug session refresh" --json
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--query TEXT` — required lexical retrieval query.
- `--limit N` — maximum findings to return; defaults to 5.
- `--include-stale` — include findings invalidated by changed/missing source or explicit supersession.
- `--json` — emit the full finding list.

Normal recall excludes stale and superseded findings. Retrieval is deterministic and local; it does not call an embedding model or remote service.

## Exit codes

- `0` — recall completed, including when no current finding matches.
- `2` — invalid arguments or local persistence failure.

## Output contract

Text mode prints score, finding ID, confidence/state, claim, anchors, and stale reasons when requested. JSON mode emits an array of finding objects with a deterministic `score`, current `state`, anchor `current_digest` values, and `stale_reasons`.

A changed anchor is not silently trusted: its finding moves to `stale` and is omitted unless `--include-stale` is supplied.

## Authoritative runtime help

```bash
token-saver recall --help
```

# `token-saver ingress-read`

Recover an exact bounded line range from an oversized prompt previously staged by the opt-in ingress optimizer.

## Synopsis

```bash
token-saver ingress-read STAGE_ID --path . --start-line 80 --end-line 140
```

## Arguments and options

- positional `STAGE_ID` — staged-prompt identifier.
- `--path PATH` — project root used to scope private staged state.
- `--start-line N` — required inclusive 1-based start line.
- `--end-line N` — required inclusive 1-based end line.

The command verifies the exact-original SHA-256 before returning source text.

## Exit codes

- `0` — exact requested range returned.
- `2` — invalid range, unknown stage, unreadable state, or integrity failure.

## Output contract

Writes the requested exact line range to stdout followed by a newline. It does not summarize, truncate, or infer omitted text.

## Authoritative runtime help

```bash
token-saver ingress-read --help
```

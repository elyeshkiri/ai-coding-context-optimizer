# `token-saver ingress-show`

Show the bounded, recoverable packet for an oversized prompt that Token Saver staged before Claude model processing.

## Synopsis

```bash
token-saver ingress-show STAGE_ID --path .
token-saver ingress-show STAGE_ID --path . --json
```

## Arguments and options

- positional `STAGE_ID` — identifier returned when the opt-in ingress hook blocks and stages an oversized prompt.
- `--path PATH` — project root used to scope private staged-prompt state; defaults to `.`.
- `--json` — emit packet metadata plus the packet as JSON.

The packet contains exact head/tail excerpts and explicit line numbers for any omitted middle span. It is not presented as a lossy replacement for the original.

## Exit codes

- `0` — stage was found and verified.
- `2` — unknown, unreadable, malformed, or integrity-failed stage.

## Output contract

Text mode prints only the staged packet. JSON mode emits `id`, timestamps, SHA-256, original/packet token estimates, original line count, packet text, and omitted line bounds. The exact original remains in private local state.

## Authoritative runtime help

```bash
token-saver ingress-show --help
```

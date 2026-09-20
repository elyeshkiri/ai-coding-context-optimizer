# `token-saver cache-economics`

Estimate whether replacing context is cheaper after prompt-cache write/read effects, including the penalty for recreating an already-cached prefix.

## Synopsis

```bash
token-saver cache-economics \
  --original-frontier-tokens 4000 \
  --replacement-frontier-tokens 800 \
  --cached-prefix-tokens 12000 \
  --expected-reuses 2

token-saver cache-economics \
  --original-frontier-tokens 4000 \
  --replacement-frontier-tokens 800 \
  --cached-prefix-tokens 12000 \
  --invalidates-cached-prefix \
  --json
```

## Arguments and options

- `--original-frontier-tokens N` — required original uncached/new-context size.
- `--replacement-frontier-tokens N` — required replacement size.
- `--cached-prefix-tokens N` — already-cached history; defaults to 0.
- `--invalidates-cached-prefix` — model the replacement as recreating that cached prefix.
- `--expected-reuses N` — expected later cache reads; defaults to 1.
- `--cache-write-factor FLOAT` — relative cache-write input cost; defaults to 1.25.
- `--cache-read-factor FLOAT` — relative cache-read input cost; defaults to 0.10.
- `--min-relative-savings FLOAT` — required savings ratio in 0..1; defaults to 0.
- `--json` — emit the complete decision object.

The default factors are relative planning values, not a claim that every provider/model has identical pricing. Supply model/provider-specific factors when using the result for a real billing decision.

## Exit codes

- `0` — economics were evaluated successfully.
- `2` — invalid token counts, factors, or savings threshold.

## Output contract

JSON output contains `accepted`, `original_cost`, `replacement_cost`, `relative_savings`, token inputs, prefix-invalidation state, expected reuses, factors, and the minimum savings threshold.

Costs are relative input-cost units. They deliberately avoid pretending that one hard-coded dollar rate applies to every provider/model.

## Authoritative runtime help

```bash
token-saver cache-economics --help
```

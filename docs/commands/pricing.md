# `acco pricing`

Inspect ACCO's packaged first-party Claude API pricing registry.

## Synopsis

```bash
acco pricing [--model MODEL] [--max-age-days N] [--require-fresh] [--json]
```

## Arguments and options

- `--model MODEL` — show one canonical model id or an explicitly declared
  alias. ACCO does not infer model aliases.
- `--max-age-days N` — override the registry freshness threshold for this
  inspection.
- `--require-fresh` — exit `1` if the registry is older than the allowed
  freshness window.
- `--json` — emit source/freshness metadata and model rate records.

The packaged registry covers standard global first-party Claude API pricing.
Batch, fast mode, US-only inference/data-residency multipliers, and
partner-operated cloud pricing are intentionally outside this registry.

Use the registry explicitly with the operational advisor:

```bash
acco cost-advisor . --rates builtin
```

Historical benchmark/evidence runs should continue to use their frozen rate
files so later upstream price changes cannot rewrite historical economics.

## Exit codes

- `0` — registry inspected successfully and any requested freshness gate passed;
- `1` — `--require-fresh` was requested and the registry is stale;
- `2` — invalid arguments, registry data, or unknown model id.

## Output contract

See [Machine-readable contracts](../JSON_OUTPUTS.md#pricing---json).

## Authoritative runtime help

Run `acco pricing --help` for the installed version.

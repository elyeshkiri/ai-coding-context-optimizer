# `acco demo`

Show ACCO's repository-context reduction locally without making a provider request.

## Synopsis

```bash
acco demo [path] [--query TEXT] [--max-tokens N] [--json]
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--query` — task/query to retrieve for. If omitted, ACCO derives a harmless
  navigation query from an indexed symbol when possible.
- `--max-tokens` — bounded context-pack budget; defaults to 6000.
- `--json` — emit the structured result.

## Exit codes

- `0` — local demonstration completed.
- `2` — invalid repository/query/budget or indexing/retrieval failure.

## Output contract

The report contains indexed-file count, a local whole-repository planning token
estimate, actual ACCO pack estimate, selected files, reduction fraction, and
`provider_request_made: false`. The whole-repository estimate uses file
bytes/4 for planning; the command explicitly does not claim task success or API
cost savings.

## Authoritative runtime help

Run `acco demo --help` for the installed version.

# `token-saver optimize`

Plan and evaluate reversible Token Saver-owned efficiency changes.

## Synopsis

```bash
token-saver optimize [path] [--days N] [--json]
token-saver optimize [path] --apply PROPOSAL_ID
token-saver optimize [path] --evaluate RUN_ID [--min-turns N]
  [--min-improvement FRACTION] [--no-auto-revert]
token-saver optimize [path] --status
```

## Arguments and options

- `path` — project root.
- `--days` — baseline evidence window; default 7.
- `--apply ID` — apply one current low-risk Token Saver config proposal.
- `--evaluate RUN_ID` — compare post-change provider-reported tokens/turn.
- `--min-turns` — minimum measured turns in each arm; default 5.
- `--min-improvement` — required fractional reduction before keeping a change.
- `--no-auto-revert` — report a failed comparison without restoring the config.
- `--status` — list private optimization journals.
- `--json` — emit the machine-readable plan/run record.

## Exit codes

`0` command completed, including evaluations that return
`insufficient-baseline` or `insufficient-treatment`; `2` means an invalid
proposal/run/configuration, malformed arguments, or another refused operation.

## Output contract

Applying a proposal first saves the exact prior config in recovery and records a
measured baseline. Evaluation keeps a change only when enough provider-reported
post-change turns beat the configured threshold; otherwise it restores the exact
previous config by default. A proposal alone is never presented as a savings claim.

## Authoritative runtime help

Run `token-saver optimize --help` for the installed version.

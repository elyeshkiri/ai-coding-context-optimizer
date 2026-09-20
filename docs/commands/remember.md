# `token-saver remember`

Persist one explicit evidence-backed project finding for later sessions. Findings are local, bounded, and anchored to current repository files; Token Saver records anchor digests so later source changes make the finding stale.

## Synopsis

```bash
token-saver remember [path] \
  --claim "Refresh tokens are rotated in auth" \
  --anchor src/auth.py::refresh_session \
  --evidence "refresh_session delegates to rotate_token" \
  --applicability "Use when changing login/session refresh behavior"
```

## Arguments and options

- `path` — repository root; defaults to `.`.
- `--claim TEXT` — required durable conclusion.
- `--anchor FILE[::SYMBOL]` — required repository evidence anchor; repeatable, maximum 8.
- `--evidence TEXT` — required observation that established the claim.
- `--applicability TEXT` — required description of when the finding is useful.
- `--confidence speculative|probable|verified` — confidence label; defaults to `verified`.
- `--invalidator TEXT` — condition that should trigger human re-validation; repeatable.
- `--supersedes ID` — older finding ID replaced by this finding; repeatable.
- `--json` — emit the complete stored finding.

Anchors must resolve to real files inside the repository. Token Saver does not persist arbitrary unanchored model prose through this command.

## Exit codes

- `0` — finding was stored or refreshed.
- `2` — arguments are invalid, an anchor is missing/outside the repository, or local persistence failed.

## Output contract

Text mode prints the finding ID, confidence, claim, and normalized anchors. JSON mode emits the stored finding including `id`, `claim`, `anchors`, `evidence`, `applicability`, `confidence`, `invalidators`, `supersedes`, timestamps, `version`, `state`, and `stale_reasons`.

Re-recording the same normalized claim and anchor identity updates one record and increments `version` instead of creating an exact duplicate.

## Authoritative runtime help

```bash
token-saver remember --help
```

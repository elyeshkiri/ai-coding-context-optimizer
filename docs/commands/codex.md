# `acco codex`

Launch Codex through ACCO's ephemeral OpenAI provider proxy.

## Synopsis

```bash
acco codex [CODEX_ARGS...]
```

## Arguments and options

All arguments after `acco codex` are forwarded to the Codex executable. The
alias itself has no wrapper-specific flags. Use `acco wrap` for wrapper
configuration.

ACCO sets `OPENAI_BASE_URL` for the child to the local proxy's `/v1` endpoint
and tears the proxy down when Codex exits. Existing credentials remain in the
child environment and are not persisted by the wrapper.

## Exit codes

Returns Codex's exit code. Wrapper startup failures return `2`.

## Output contract

The alias does not rewrite Codex stdout/stderr. It is equivalent to
`acco wrap codex -- CODEX_ARGS...` with provider model routing off by default.

## Authoritative runtime help

Run `acco wrap --help` for ACCO wrapper controls and `codex --help` for
forwarded Codex arguments.

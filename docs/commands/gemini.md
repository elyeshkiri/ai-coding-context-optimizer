# `acco gemini`

Launch Gemini CLI through ACCO's ephemeral Gemini provider proxy.

## Synopsis

```bash
acco gemini [GEMINI_ARGS...]
```

## Arguments and options

All arguments after `acco gemini` are forwarded to the Gemini executable. The
alias itself has no wrapper-specific flags. Use `acco wrap` for wrapper
configuration.

ACCO sets `GOOGLE_GEMINI_BASE_URL` only for the child process and tears the
loopback proxy down when Gemini exits. Existing credentials remain in the child
environment and are not written by the wrapper.

## Exit codes

Returns Gemini CLI's exit code. Wrapper startup failures return `2`.

## Output contract

The alias does not rewrite Gemini stdout/stderr. It is equivalent to
`acco wrap gemini -- GEMINI_ARGS...` with provider model routing off by
default.

## Authoritative runtime help

Run `acco wrap --help` for ACCO wrapper controls and `gemini --help` for
forwarded Gemini arguments.

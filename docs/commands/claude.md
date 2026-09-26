# `acco claude`

Launch Claude Code through ACCO's ephemeral Anthropic provider proxy.

## Synopsis

```bash
acco claude [CLAUDE_ARGS...]
```

## Arguments and options

All arguments after `acco claude` are forwarded to the Claude executable. The
alias itself has no wrapper-specific flags. Use `acco wrap` when you need a
custom port, dry-run, upstream, or routing mode.

ACCO sets `ANTHROPIC_BASE_URL` only for the child process, keeps the proxy
loopback-only, and terminates it when Claude exits. Existing credentials remain
in the child environment and are not written by the wrapper.

## Exit codes

Returns Claude's exit code. Wrapper startup failures return `2`.

## Output contract

The alias does not rewrite Claude's stdout/stderr. It is equivalent to
`acco wrap claude -- CLAUDE_ARGS...` with provider model routing off by
default.

## Authoritative runtime help

Run `acco wrap --help` for ACCO wrapper controls and `claude --help` for
forwarded Claude arguments.

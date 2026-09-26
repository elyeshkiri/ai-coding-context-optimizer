# `acco claude`

Launch Claude Code through ACCO's ephemeral Anthropic provider proxy.

```bash
acco claude
acco claude --help
```

This is the low-friction alias for `acco wrap claude -- ...`. ACCO sets
`ANTHROPIC_BASE_URL` only for the child process, keeps the proxy loopback-only,
and terminates it when Claude exits. Existing credentials remain in the child
environment and are not written by the wrapper.

Provider model routing remains off by default. Use `acco wrap` directly when
you need wrapper-specific options such as calibrated routing or a custom port.

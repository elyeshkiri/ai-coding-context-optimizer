# `acco codex`

Launch Codex through ACCO's ephemeral OpenAI provider proxy.

```bash
acco codex
acco codex --help
```

This is the low-friction alias for `acco wrap codex -- ...`. ACCO sets
`OPENAI_BASE_URL` for the child to the local proxy's `/v1` endpoint and
terminates the proxy when Codex exits. Existing credentials remain in the child
environment and are not persisted by the wrapper.

Provider model routing remains off by default. Use `acco wrap` directly for
wrapper-specific controls.

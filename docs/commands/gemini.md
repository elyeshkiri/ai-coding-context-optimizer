# `acco gemini`

Launch Gemini CLI through ACCO's ephemeral Gemini provider proxy.

```bash
acco gemini
acco gemini --help
```

This is the low-friction alias for `acco wrap gemini -- ...`. ACCO sets
`GOOGLE_GEMINI_BASE_URL` only for the child process and tears the loopback
proxy down on exit. Existing credentials remain in the child environment and
are not written by the wrapper.

Provider model routing remains off by default. Use `acco wrap` directly for
wrapper-specific controls.

# `acco wrap`

Launch a coding-agent process through an ephemeral loopback ACCO provider proxy.

```bash
acco wrap claude
acco wrap codex -- --help
acco wrap gemini
acco wrap --dry-run --json claude
```

Presets use the provider's documented base-URL environment variable:

- Claude: `ANTHROPIC_BASE_URL`
- Codex/OpenAI: `OPENAI_BASE_URL` (the local URL includes `/v1`)
- Gemini CLI: `GOOGLE_GEMINI_BASE_URL`

The child inherits the existing environment, including credentials. ACCO does
not copy credentials into files. The proxy listens on loopback by default and
is terminated when the child exits.

Model routing defaults to `off`. Use `--model-routing observe` or
`--model-routing calibrated` explicitly when desired.

Unknown agents require explicit `--provider`, `--upstream`, and
`--base-url-env` values. `--dry-run` prints the plan without launching
anything.

The short commands `acco claude`, `acco codex`, and `acco gemini` dispatch
through the same wrapper.

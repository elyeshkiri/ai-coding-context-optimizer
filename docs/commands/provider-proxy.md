# `token-saver provider-proxy`

Run the opt-in local provider optimization reverse proxy.

## Synopsis

```bash
token-saver provider-proxy [path] --upstream URL [--provider NAME]
  [--bind IP] [--port N] [--tool-result-min-tokens N]
  [--timeout-seconds SECONDS]
  [--no-schema-compression] [--no-tool-result-compression]
  [--no-prefix-tracking] [--allow-non-loopback]
```

## Arguments and options

- `path` — project root for recovery/prefix state.
- `--upstream URL` — provider origin. HTTPS is required except localhost.
- `--provider` — `generic`, `anthropic`, `openai`, or `gemini`.
- `--bind` / `--port` — local listener; loopback is the safe default.
- `--tool-result-min-tokens` — minimum large tool-result size before compression.
- `--timeout-seconds` — upstream request timeout; default 120 seconds.
- `--no-schema-compression` — preserve incoming tool catalogs byte-for-byte.
- `--no-tool-result-compression` — disable historical tool-result transforms.
- `--no-prefix-tracking` — disable content-free stable-prefix hit/miss telemetry.
- `--allow-non-loopback` — explicitly permit a non-loopback listener; the user
  is responsible for access control.

## Exit codes

Runs until interrupted. `2` rejects unsafe/invalid configuration.

## Output contract

Provider responses are forwarded unchanged. Supported JSON requests may be
transformed before forwarding; every lossy payload transformation requires exact
local recovery. Unsupported/non-JSON requests pass through. Automatic upstream
redirect following is disabled so authorization headers cannot be forwarded to a
different redirect origin; redirects are returned to the client.

## Authoritative runtime help

Run `token-saver provider-proxy --help` for the installed version.

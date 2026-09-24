# `acco provider-proxy`

Run the opt-in local provider optimization reverse proxy.

## Synopsis

```bash
acco provider-proxy [path] --upstream URL [--provider NAME]
  [--bind IP] [--port N] [--tool-result-min-tokens N]
  [--timeout-seconds SECONDS]
  [--no-schema-compression] [--no-tool-result-compression]
  [--no-prefix-tracking] [--no-usage-telemetry] [--allow-non-loopback]
```

## Arguments and options

- `path` — project root for recovery/prefix state.
- `--upstream URL` — provider origin. HTTPS is required except localhost.
- `--provider` — `auto` (default), `generic`, `anthropic`, `openai`, or
  `gemini`. Auto mode recognizes Anthropic Messages, OpenAI Chat Completions /
  Responses, and Gemini generateContent/streamGenerateContent request paths.
- `--bind` / `--port` — local listener; loopback is the safe default.
- `--tool-result-min-tokens` — minimum large tool-result size before compression.
- `--timeout-seconds` — upstream request timeout; default 120 seconds.
- `--no-schema-compression` — preserve incoming tool catalogs byte-for-byte.
- `--no-tool-result-compression` — disable historical tool-result transforms.
- `--no-prefix-tracking` — disable content-free stable-prefix hit/miss telemetry.
- `--no-usage-telemetry` — disable content-free provider response token/model
  counters. Response bytes are still forwarded unchanged.
- `--allow-non-loopback` — explicitly permit a non-loopback listener; the user
  is responsible for access control.

## Exit codes

Runs until interrupted. `2` rejects unsafe/invalid configuration.

## Output contract

Provider responses are forwarded byte-for-byte; streaming responses are not
buffered or rewritten. ACCO may observe provider-reported usage counters while
those bytes pass and stores only content-free metadata such as provider, request
shape, model id, input/output/cache token counters, and whether the request was
streaming.

The request transform remains retrieval-first. It may reduce tool catalogs and
**historical** tool/function outputs, but it does not rewrite the current user
instruction, fresh repository/source excerpts, or ordinary assistant messages.
OpenAI Responses `function_call_output`, Anthropic/Chat tool-result messages,
and Gemini `functionResponse` string leaves share the same exact-recovery
contract. Nested OpenAI `function.parameters` and Gemini
`functionDeclarations` schemas are compressed conservatively without renaming
construction fields.

Unsupported/non-JSON requests pass through. Automatic upstream redirect
following is disabled so authorization headers cannot be forwarded to a
different redirect origin; redirects are returned to the client.

## Authoritative runtime help

Run `acco provider-proxy --help` for the installed version.

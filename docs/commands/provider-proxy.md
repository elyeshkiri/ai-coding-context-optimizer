# `acco provider-proxy`

Run the opt-in local provider optimization reverse proxy.

## Synopsis

```bash
acco provider-proxy [path] --upstream URL [--provider NAME]
  [--bind IP] [--port N] [--tool-result-min-tokens N]
  [--timeout-seconds SECONDS]
  [--no-schema-compression] [--no-tool-result-compression]
  [--no-history-dedup]
  [--model-routing off|observe|calibrated]
  [--routing-calibration-file FILE] [--routing-min-savings FRACTION]
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
- `--no-tool-result-compression` — disable semantic/structural historical
  tool-result compression.
- `--no-history-dedup` — disable exact duplicate historical tool-result
  suppression. By default ACCO keeps the first copy, replaces later byte-identical
  large copies with a compact recovery pointer, and stores the original bytes in
  the local recovery store.
- `--model-routing` — `off` (default), `observe`, or `calibrated`.
  `observe` records routing opportunities without changing the request model.
  `calibrated` may switch an Anthropic request to a cheaper ACCO-profiled model
  only when an accepted quality-gated routing calibration admits that exact
  task/complexity/risk bucket. Static heuristics alone never trigger an automatic
  downgrade.
- `--routing-calibration-file` — quality-gated routing artifact; defaults to
  `.acco.routing-calibration.json`.
- `--routing-min-savings` — minimum projected one-turn cost reduction before a
  model switch is useful; default 0.05.
- `--no-prefix-tracking` — disable content-free stable-prefix telemetry.
  Prefix tracking distinguishes exact reuse from normal append-only history
  extension so cache-friendly conversations are not counted as false misses.
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

The request transform remains retrieval-first. It may reduce tool catalogs,
deduplicate or compress **historical** tool/function outputs, but it does not
rewrite the current user instruction, fresh repository/source excerpts, or
ordinary assistant messages. Exact duplicate suppression is lossless through
the local `acco recover` handle.
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


## Everyday-cost safety boundaries

The proxy separates three different cost mechanisms instead of treating every
token reduction as equivalent:

1. **Historical context reduction** removes redundant/noisy tool payloads before
   they are sent again, with exact recovery for lossy transforms.
2. **Prefix preservation telemetry** detects exact and append-only reuse without
   persisting request text. It is observational; ACCO does not claim provider
   cache billing from the hash alone.
3. **Model routing** is opt-in. Automatic downgrade is restricted to
   `calibrated` mode and accepted frozen paired evidence. If calibration is
   absent, invalid, stale for the exact bucket, or the current model is not an
   exact ACCO profile, the caller's model is preserved.

These controls never make verification optional. ACCO's generation policy still
requires the existing tests relevant to touched code before a coding task is
finished; it merely asks the agent to start with the smallest directly relevant
verification target and expand when risk, failures, or project policy require it.

Project configuration equivalents live under `[provider]`:

```toml
[provider]
history_dedup = true
prefix_tracking = true
model_routing = "off" # "observe" or "calibrated"
routing_calibration_file = ".acco.routing-calibration.json"
routing_min_savings = 0.05
```

Environment overrides are `ACCO_PROVIDER_HISTORY_DEDUP`,
`ACCO_PREFIX_TRACKING`, `ACCO_PROVIDER_MODEL_ROUTING`,
`ACCO_PROVIDER_ROUTING_CALIBRATION_FILE`, and
`ACCO_PROVIDER_ROUTING_MIN_SAVINGS`.

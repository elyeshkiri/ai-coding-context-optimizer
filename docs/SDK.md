# Middleware SDKs

ACCO can be embedded in custom agents without routing the agent through a coding
CLI. The SDK surface deliberately reuses the same provider transform, context
router, output processors, model-routing policy, and exact-recovery store used
by ACCO's built-in integrations.

## Python: in-process engine

```python
from acco.sdk import AccoEngine

acco = AccoEngine("/path/to/project")
middleware = acco.middleware("anthropic")

prepared = middleware.before_request({
    "messages": [
        {"role": "user", "content": "Fix the failing authentication test"}
    ]
})

tool = middleware.after_tool_result(
    raw_tool_output,
    query="Fix the failing authentication test",
    command="pytest -q",
)

request_body = prepared["body"]
tool_text = tool["text"]

if tool["recovery_handle"]:
    exact = middleware.recover(tool["recovery_handle"])
    assert exact["encoding"] == "utf-8"
    raw_tool_output = exact["payload"]
```

Python callers can also use the engine directly:

```python
acco.optimize_provider_request("openai", body)
acco.optimize_context(text, query=prompt, command="rg auth")
acco.optimize_output(stdout, command="pytest -q", exit_code=1)
acco.route_model(prompt, current_model="claude-sonnet-5")
acco.recover("tsr_...")
```

### Python middleware lifecycle

`AccoMiddleware` intentionally stays framework-neutral:

- `before_request(body, **options)` optimizes one provider-bound request;
- `after_tool_result(text, ...)` prepares large tool context before the next
  model call;
- `route(prompt, **options)` returns a deterministic model-routing decision
  for orchestrators that can choose a model;
- `recover(handle)` returns the exact source bytes represented by an accepted
  lossy transform.

The middleware does not send requests to a provider. Your agent remains in
control of provider authentication, retries, streaming, and model execution.

## TypeScript: typed local client

The repository contains a typed package at `sdk/typescript`. It does not port
ACCO's optimization algorithms to JavaScript; that would create two engines
whose safety and recovery behavior could drift. Instead, TypeScript agents talk
to the same Python engine over a small versioned loopback API.

Start the bridge:

```bash
pip install acco
acco sdk-serve /path/to/project
```

Then use the client:

```ts
import { AccoClient } from "@acco-ai/sdk";

const acco = new AccoClient({
  baseUrl: "http://127.0.0.1:8770",
});

const middleware = acco.middleware("anthropic");

const prepared = await middleware.beforeRequest(requestBody);

const tool = await middleware.afterToolResult({
  text: rawToolOutput,
  query: userPrompt,
  command: "pytest -q",
});

const route = await middleware.route(userPrompt, {
  current_model: "claude-sonnet-5",
});

if (tool.recovery_handle) {
  const exact = await middleware.recover(tool.recovery_handle);
}
```

The TypeScript runtime has no third-party production dependencies. The package
ships typed declarations and tests the published JavaScript runtime contract.

For provider SDKs that accept a custom `fetch` implementation, ACCO can
intercept the request boundary without changing the provider base URL:

```ts
const providerFetch = acco.interceptFetch("openai");

// Example: pass providerFetch as the SDK/client fetch implementation.
```

The interceptor touches only JSON request bodies, routes them through
`/v1/provider/optimize`, removes stale `content-length`, and then calls the
original provider fetch. If the local ACCO bridge is unavailable it fails open
to the untouched request by default; pass `{ failOpen: false }` when a caller
prefers strict failure. Non-JSON, GET, HEAD, streaming response, authentication,
retry, and provider transport semantics remain owned by the provider client.

## HTTP contract

The bridge exposes only versioned JSON endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/v1/health` | health/version/project identity |
| `POST` | `/v1/provider/optimize` | optimize provider request JSON |
| `POST` | `/v1/context/optimize` | recoverable arbitrary/tool context |
| `POST` | `/v1/output/optimize` | command-aware output optimization |
| `POST` | `/v1/route` | deterministic model-routing decision |
| `POST` | `/v1/recover` | exact recovery by `tsr_...` handle |

The request limit is 32 MiB. The service returns JSON only and does not log
request bodies.

## Safety and recovery guarantees

The SDK does not weaken ACCO's existing transformation rules:

1. A provider/context transform is accepted only when the result is smaller.
2. Lossy context/provider transformations require exact local recovery first.
3. SDK output compression with `recoverable=true` also fails open to the
   original text if the recovery store has insufficient capacity.
4. Model routing is the existing deterministic ACCO policy. A route decision is
   not an independent benchmark of model quality.
5. The TypeScript bridge binds to `127.0.0.1` by default.

The bridge has no built-in remote authentication because it is designed as a
local process boundary. `--allow-non-loopback` is explicit and should only be
used behind operator-provided authentication/TLS/access controls.

## Framework adapters

The first SDK release intentionally exposes neutral lifecycle primitives rather
than hard-coding LangChain, Vercel AI SDK, CrewAI, AutoGen, or another framework.
A framework adapter can map its hooks to `before_request` /
`after_tool_result` (Python) or `beforeRequest` /
`afterToolResult` (TypeScript) without changing ACCO internals.

This keeps framework-specific dependencies outside the core package and makes
future adapters thin, separately testable compatibility layers.

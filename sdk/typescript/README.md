# @acco-ai/sdk

Typed, dependency-free JavaScript/TypeScript middleware client for ACCO.

The TypeScript SDK intentionally does **not** reimplement ACCO's optimization
algorithms. Start the local Python engine:

```bash
pip install acco
acco sdk-serve .
```

Then call it from a custom agent:

```ts
import { AccoClient } from "@acco-ai/sdk";

const acco = new AccoClient();
const middleware = acco.middleware("anthropic");

const prepared = await middleware.beforeRequest(requestBody);
const optimizedTool = await middleware.afterToolResult({
  text: rawToolOutput,
  query: userPrompt,
  command: "pytest -q",
});

if (optimizedTool.recovery_handle) {
  const exact = await middleware.recover(optimizedTool.recovery_handle);
}
```

The service binds to loopback by default. Do not expose it on a network without
your own authentication and transport controls.

For clients that accept a custom `fetch`, intercept the provider boundary
without changing its base URL:

```ts
const providerFetch = acco.interceptFetch("openai");
```

Only JSON model requests are eligible. Accepted transforms target provider tool
schemas and historical tool/function results; current user/source context is not
rewritten. If ACCO accepts no transform, the original request bytes are passed
through. If the local bridge is unavailable, the interceptor fails open by
default.

import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { AccoClient, AccoSdkError } from "../dist/index.js";

function withServer(handler, run) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", async () => {
      try {
        const address = server.address();
        const result = await run(`http://127.0.0.1:${address.port}`);
        server.close(() => resolve(result));
      } catch (error) {
        server.close(() => reject(error));
      }
    });
  });
}

test("typed client sends provider optimization contract", async () => {
  await withServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    assert.equal(req.url, "/v1/provider/optimize");
    assert.equal(body.provider, "anthropic");
    assert.equal(body.body.messages[0].role, "user");
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ schema: 1, body: body.body, metadata: { changed: false } }));
  }, async (baseUrl) => {
    const client = new AccoClient({ baseUrl });
    const result = await client.optimizeRequest("anthropic", {
      messages: [{ role: "user", content: "hello" }],
    });
    assert.equal(result.schema, 1);
    assert.equal(result.metadata.changed, false);
  });
});

test("middleware binds provider and exposes tool optimization", async () => {
  const paths = [];
  await withServer(async (req, res) => {
    paths.push(req.url);
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    res.writeHead(200, { "content-type": "application/json" });
    if (req.url === "/v1/provider/optimize") {
      assert.equal(body.provider, "openai");
      res.end(JSON.stringify({ schema: 1, body: body.body, metadata: {} }));
    } else {
      assert.equal(body.command, "pytest -q");
      res.end(JSON.stringify({
        schema: 1,
        text: body.text,
        kind: "plain",
        changed: false,
        original_tokens: 1,
        output_tokens: 1,
        recovery_handle: null,
        metadata: {},
      }));
    }
  }, async (baseUrl) => {
    const middleware = new AccoClient({ baseUrl }).middleware("openai");
    await middleware.beforeRequest({ input: [] });
    await middleware.afterToolResult({ text: "ok", command: "pytest -q" });
  });
  assert.deepEqual(paths, ["/v1/provider/optimize", "/v1/context/optimize"]);
});

test("non-2xx responses preserve structured SDK error", async () => {
  await withServer((_req, res) => {
    res.writeHead(400, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "invalid_request", message: "bad payload" }));
  }, async (baseUrl) => {
    const client = new AccoClient({ baseUrl });
    await assert.rejects(
      () => client.recover("bad"),
      (error) =>
        error instanceof AccoSdkError &&
        error.status === 400 &&
        error.message === "bad payload",
    );
  });
});


test("provider fetch interceptor optimizes JSON and fails open by default", async () => {
  await withServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (req.url === "/v1/provider/optimize") {
      assert.equal(body.provider, "openai");
      const optimized = structuredClone(body.body);
      optimized.marker = "optimized";
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        schema: 1,
        body: optimized,
        metadata: { changed: true },
      }));
      return;
    }
    res.writeHead(404);
    res.end();
  }, async (baseUrl) => {
    const seen = [];
    const upstream = async (input, init) => {
      seen.push({
        url: String(input),
        body: init?.body ?? null,
      });
      return new Response("ok", { status: 200 });
    };
    const client = new AccoClient({ baseUrl });
    const intercepted = client.interceptFetch("openai", { fetchImpl: upstream });
    await intercepted("https://api.openai.test/v1/responses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ input: "hello" }),
    });
    assert.equal(JSON.parse(seen[0].body).marker, "optimized");
  });

  const failingClient = new AccoClient({
    baseUrl: "http://127.0.0.1:1",
    timeoutMs: 50,
  });
  const seen = [];
  const upstream = async (input, init) => {
    seen.push(init?.body ?? null);
    return new Response("ok", { status: 200 });
  };
  const intercepted = failingClient.interceptFetch("anthropic", {
    fetchImpl: upstream,
  });
  const original = JSON.stringify({ messages: [{ role: "user", content: "hello" }] });
  await intercepted("https://api.anthropic.test/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: original,
  });
  assert.equal(seen[0], original);
});

test("provider fetch interceptor preserves original JSON bytes on ACCO no-op", async () => {
  await withServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      schema: 1,
      body: body.body,
      metadata: { changed: false },
    }));
  }, async (baseUrl) => {
    const seen = [];
    const upstream = async (_input, init) => {
      seen.push(init?.body ?? null);
      return new Response("ok", { status: 200 });
    };
    const client = new AccoClient({ baseUrl });
    const intercepted = client.interceptFetch("openai", { fetchImpl: upstream });
    const original = '{ "input": "hello", "temperature": 0 }';
    await intercepted("https://api.openai.test/v1/responses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: original,
    });
    assert.equal(seen[0], original);
  });
});

test("provider fetch interceptor can fail closed when explicitly requested", async () => {
  const client = new AccoClient({
    baseUrl: "http://127.0.0.1:1",
    timeoutMs: 50,
  });
  const intercepted = client.interceptFetch("openai", {
    fetchImpl: async () => new Response("unexpected"),
    failOpen: false,
  });
  await assert.rejects(
    () => intercepted("https://api.openai.test/v1/responses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ input: "hello" }),
    }),
  );
});

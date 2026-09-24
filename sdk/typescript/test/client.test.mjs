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

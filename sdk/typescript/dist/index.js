export class AccoSdkError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "AccoSdkError";
    this.status = status;
    this.payload = payload;
  }
}

export class AccoClient {
  constructor(options = {}) {
    const baseUrl = (options.baseUrl ?? "http://127.0.0.1:8770").replace(/\/+$/, "");
    const parsed = new URL(baseUrl);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new TypeError("ACCO SDK baseUrl must use http or https");
    }
    this.baseUrl = baseUrl;
    this.timeoutMs = options.timeoutMs ?? 120_000;
    if (!Number.isFinite(this.timeoutMs) || this.timeoutMs <= 0) {
      throw new TypeError("ACCO SDK timeoutMs must be positive");
    }
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async request(method, path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(this.baseUrl + path, {
        method,
        headers: body ? { "content-type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      const raw = await response.text();
      let payload = {};
      if (raw) {
        try {
          payload = JSON.parse(raw);
        } catch {
          throw new AccoSdkError("ACCO SDK returned invalid JSON", response.status, raw);
        }
      }
      if (!response.ok) {
        const detail =
          payload && typeof payload === "object" && "message" in payload
            ? String(payload.message ?? "")
            : "";
        throw new AccoSdkError(
          detail || `ACCO SDK request failed with HTTP ${response.status}`,
          response.status,
          payload,
        );
      }
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  health() {
    return this.request("GET", "/v1/health");
  }

  optimizeRequest(provider, body, options = {}) {
    return this.request("POST", "/v1/provider/optimize", {
      provider,
      body,
      options,
    });
  }

  optimizeContext(text, query = "", command = "", options = {}) {
    return this.request("POST", "/v1/context/optimize", {
      text,
      query,
      command,
      options,
    });
  }

  optimizeOutput(text, command = "", exitCode = null, options = {}) {
    const payload = { text, command, options };
    if (exitCode !== null) payload.exit_code = exitCode;
    return this.request("POST", "/v1/output/optimize", payload);
  }

  routeModel(prompt, options = {}) {
    return this.request("POST", "/v1/route", { prompt, options });
  }

  recover(handle) {
    return this.request("POST", "/v1/recover", { handle });
  }

  middleware(provider) {
    if (!provider.trim()) throw new TypeError("provider must be nonempty");
    return {
      beforeRequest: (body, options = {}) =>
        this.optimizeRequest(provider, body, options),
      afterToolResult: (result) =>
        this.optimizeContext(
          result.text,
          result.query ?? "",
          result.command ?? "",
          result.options ?? {},
        ),
      route: (prompt, options = {}) => this.routeModel(prompt, options),
      recover: (handle) => this.recover(handle),
    };
  }
}

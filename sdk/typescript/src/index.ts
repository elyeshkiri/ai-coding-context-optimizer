export type JsonObject = Record<string, unknown>;

export interface AccoClientOptions {
  baseUrl?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface ProviderOptimization {
  schema: number;
  body: JsonObject;
  metadata: JsonObject;
}

export interface ContextOptimization {
  schema: number;
  text: string;
  kind: string;
  changed: boolean;
  original_tokens: number;
  output_tokens: number;
  recovery_handle: string | null;
  metadata: JsonObject;
}

export interface OutputOptimization {
  schema: number;
  text: string;
  processor: string;
  changed: boolean;
  compressed: boolean;
  failed: boolean;
  recovered_lines: string[];
  original_tokens: number;
  output_tokens: number;
  recovery_handle: string | null;
}

export interface RecoveryResult {
  schema: number;
  handle: string;
  content_type: string;
  encoding: "utf-8" | "base64";
  payload: string;
  size_bytes: number;
  metadata: JsonObject;
  created_at: number;
  last_accessed_at: number | null;
  access_count: number;
}

export interface ModelRouteDecision {
  [key: string]: unknown;
  selected_model: string | null;
  current_model: string | null;
  action: "recommend" | "keep" | "route" | "manual";
}

export interface ToolResultInput {
  text: string;
  query?: string;
  command?: string;
  options?: JsonObject;
}

export interface AccoMiddleware {
  beforeRequest(
    body: JsonObject,
    options?: JsonObject,
  ): Promise<ProviderOptimization>;
  afterToolResult(result: ToolResultInput): Promise<ContextOptimization>;
  route(
    prompt: string,
    options?: JsonObject,
  ): Promise<ModelRouteDecision>;
  recover(handle: string): Promise<RecoveryResult>;
}

export class AccoSdkError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "AccoSdkError";
    this.status = status;
    this.payload = payload;
  }
}

export class AccoClient {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AccoClientOptions = {}) {
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

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: JsonObject,
  ): Promise<T> {
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
      let payload: unknown = {};
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
            ? String((payload as { message?: unknown }).message ?? "")
            : "";
        throw new AccoSdkError(
          detail || `ACCO SDK request failed with HTTP ${response.status}`,
          response.status,
          payload,
        );
      }
      return payload as T;
    } finally {
      clearTimeout(timer);
    }
  }

  health(): Promise<JsonObject> {
    return this.request<JsonObject>("GET", "/v1/health");
  }

  optimizeRequest(
    provider: string,
    body: JsonObject,
    options: JsonObject = {},
  ): Promise<ProviderOptimization> {
    return this.request("POST", "/v1/provider/optimize", {
      provider,
      body,
      options,
    });
  }

  optimizeContext(
    text: string,
    query = "",
    command = "",
    options: JsonObject = {},
  ): Promise<ContextOptimization> {
    return this.request("POST", "/v1/context/optimize", {
      text,
      query,
      command,
      options,
    });
  }

  optimizeOutput(
    text: string,
    command = "",
    exitCode: number | null = null,
    options: JsonObject = {},
  ): Promise<OutputOptimization> {
    const payload: JsonObject = { text, command, options };
    if (exitCode !== null) payload.exit_code = exitCode;
    return this.request("POST", "/v1/output/optimize", payload);
  }

  routeModel(
    prompt: string,
    options: JsonObject = {},
  ): Promise<ModelRouteDecision> {
    return this.request("POST", "/v1/route", { prompt, options });
  }

  recover(handle: string): Promise<RecoveryResult> {
    return this.request("POST", "/v1/recover", { handle });
  }

  middleware(provider: string): AccoMiddleware {
    if (!provider.trim()) throw new TypeError("provider must be nonempty");
    return {
      beforeRequest: (body: JsonObject, options: JsonObject = {}) =>
        this.optimizeRequest(provider, body, options),
      afterToolResult: (result: ToolResultInput) =>
        this.optimizeContext(
          result.text,
          result.query ?? "",
          result.command ?? "",
          result.options ?? {},
        ),
      route: (prompt: string, options: JsonObject = {}) =>
        this.routeModel(prompt, options),
      recover: (handle: string) => this.recover(handle),
    };
  }
}

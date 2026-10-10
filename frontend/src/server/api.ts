/**
 * Calls from the web server to the API (design portal-shell, decision 2). Used by the session handlers and the
 * refresh; the relay streams instead. A network failure or the time limit raises `ApiUnavailable`.
 */
import { serverConfig } from "./config";

export class ApiUnavailable extends Error {
  constructor(message = "the API is not reachable") {
    super(message);
    this.name = "ApiUnavailable";
  }
}

export interface ClientContext {
  userAgent?: string | null;
  forwardedFor?: string | null;
}

export interface ApiCall extends ClientContext {
  method: string;
  path: string;
  body?: unknown;
  token?: string;
  deviceToken?: string;
}

export interface ApiAnswer {
  status: number;
  data: unknown;
  headers: Headers;
}

/** The browser's address as the Next.js server reports it (the first `X-Forwarded-For` entry). */
export function clientAddress(request: Request): string | null {
  const forwarded = request.headers.get("x-forwarded-for");
  const first = forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip")?.trim() || "";
  if (!first) return null;
  return first.startsWith("::ffff:") ? first.slice(7) : first;
}

export function clientContext(request: Request): ClientContext {
  return { userAgent: request.headers.get("user-agent"), forwardedFor: clientAddress(request) };
}

export function upstreamHeaders(ctx: ClientContext, token?: string, deviceToken?: string): Headers {
  const headers = new Headers({ Accept: "application/json" });
  if (ctx.userAgent) headers.set("User-Agent", ctx.userAgent);
  if (ctx.forwardedFor) headers.set("X-Forwarded-For", ctx.forwardedFor);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (deviceToken) headers.set("X-Device-Token", deviceToken);
  return headers;
}

export async function callApi(call: ApiCall): Promise<ApiAnswer> {
  const config = serverConfig();
  const headers = upstreamHeaders(call, call.token, call.deviceToken);
  let body: string | undefined;
  if (call.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(call.body);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.relayTimeoutMs);
  let response: Response;
  try {
    response = await fetch(config.apiBaseUrl + call.path, {
      method: call.method,
      headers,
      body,
      signal: controller.signal,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    throw new ApiUnavailable();
  } finally {
    clearTimeout(timer);
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  return { status: response.status, data, headers: response.headers };
}

/** The `code` of an API error body, whatever its shape. */
export function errorCode(data: unknown): string | undefined {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const code = (detail as { code: unknown }).code;
      return typeof code === "string" ? code : undefined;
    }
  }
  return undefined;
}

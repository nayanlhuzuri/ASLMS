/**
 * A scripted stand-in for the API in the web-server tests: `fetch` is replaced, each call is recorded and answered
 * by the first matching route.
 */
import { vi } from "vitest";

export interface Recorded {
  url: string;
  path: string;
  method: string;
  headers: Headers;
  body: string | null;
}

type Handler = (call: Recorded) => Response | Promise<Response>;

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export function fakeApi(base = "http://api.test") {
  const calls: Recorded[] = [];
  const routes: { method: string; path: string; handler: Handler }[] = [];
  let down = false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const headers = new Headers(init?.headers);
    let body: string | null = null;
    if (init?.body !== undefined && init.body !== null) {
      body = await new Response(init.body as BodyInit).text();
    }
    const parsed = new URL(url);
    const call: Recorded = { url, path: parsed.pathname, method: (init?.method || "GET").toUpperCase(), headers, body };
    calls.push(call);
    if (down) throw new TypeError("fetch failed");
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
    const route = routes.find((r) => r.method === call.method && r.path === call.path);
    if (!route) return jsonResponse(404, { detail: "Not Found" });
    return route.handler(call);
  });
  vi.stubGlobal("fetch", fetchMock);
  process.env.API_BASE_URL = base;
  return {
    calls,
    fetchMock,
    on(method: string, path: string, handler: Handler) {
      routes.unshift({ method, path, handler });
      return this;
    },
    setDown(value: boolean) {
      down = value;
    },
  };
}

export function cookieHeader(cookies: Record<string, string>): string {
  return Object.entries(cookies)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("; ");
}

export function setCookies(response: Response): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of response.headers.getSetCookie()) {
    const [pair] = line.split(";");
    const i = pair!.indexOf("=");
    out[pair!.slice(0, i)] = line;
  }
  return out;
}

export const PORTAL = "http://localhost:3000";

export function portalRequest(
  path: string,
  init: RequestInit & { cookies?: Record<string, string>; portal?: boolean } = {},
): Request {
  const headers = new Headers(init.headers);
  if (init.cookies) headers.set("cookie", cookieHeader(init.cookies));
  const method = (init.method || "GET").toUpperCase();
  if (init.portal !== false && method !== "GET") {
    headers.set("x-aslms-request", "1");
    headers.set("origin", PORTAL);
  }
  return new Request(PORTAL + path, { ...init, headers, ...(init.body ? { duplex: "half" } : {}) } as RequestInit);
}

/**
 * The relay `/api/backend/{path}` → API `/{path}` (design portal-shell, decisions 4-7). It adds the bearer token
 * from the session cookie, the device token and the client address; it never forwards the browser's cookies or
 * `Authorization`, never returns `Set-Cookie` from the API, and refuses the token-returning operations, the auth
 * endpoints and the API documentation.
 */
import { clientAddress, upstreamHeaders } from "./api";
import { serverConfig } from "./config";
import { csrfRefusal } from "./csrf";
import { refreshOnce, type RefreshResult } from "./refresh";
import { jsonError } from "./respond";
import { clearSession, readSession, setTokens, type Session } from "./session";
import tokenRoutes from "./token-routes.json";

export const RELAY_PREFIX = "/api/backend";

// `content-length` lets the API refuse an oversized upload before reading it (design portal-workflow, decision 23)
const REQUEST_HEADERS = ["content-type", "content-length", "accept", "user-agent"] as const;
const RESPONSE_HEADERS = [
  "content-type",
  "content-length",
  "content-disposition",
  "cache-control",
  "retry-after",
  "x-total-count",
  // a document viewed inline keeps the API's protection (design portal-cases, decision 15)
  "x-content-type-options",
  "content-security-policy",
] as const;
const DENY_PREFIXES = ["/auth", "/docs", "/redoc"];
const DENY_EXACT = new Set(["/openapi.json", "/me/password", ...tokenRoutes.routes.map((r) => r.path.toLowerCase())]);

export function isDenied(path: string): boolean {
  const p = path.toLowerCase().replace(/\/+$/, "") || "/";
  if (DENY_EXACT.has(p)) return true;
  return DENY_PREFIXES.some((prefix) => p === prefix || p.startsWith(prefix + "/"));
}

/** The raw path and query of a URL string, before any normalisation of dot segments. */
function rawPathAndQuery(url: string): { path: string; query: string } {
  const withoutOrigin = url.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/?#]*/i, "");
  const hashless = withoutOrigin.split("#")[0] ?? "";
  const q = hashless.indexOf("?");
  return q < 0 ? { path: hashless, query: "" } : { path: hashless.slice(0, q), query: hashless.slice(q) };
}

/**
 * The API path for a relay request, or null when it must be refused: `..` or `.` segments (plain or encoded), an
 * encoded slash or backslash, a backslash, `//`, or a denylisted path.
 */
export function targetPath(url: string): string | null {
  const { path, query } = rawPathAndQuery(url);
  if (!path.startsWith(RELAY_PREFIX + "/")) return null;
  const rest = path.slice(RELAY_PREFIX.length);
  if (rest.includes("//") || rest.includes("\\")) return null;
  if (/%2f|%5c/i.test(rest)) return null;
  const segments = rest.slice(1).split("/");
  for (const segment of segments) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      return null;
    }
    if (decoded === "" || decoded === "." || decoded === ".." || decoded.includes("/")) {
      if (decoded === "" && segment === segments[segments.length - 1] && segments.length > 1) continue;
      return null;
    }
  }
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(rest);
  } catch {
    return null;
  }
  if (isDenied(decodedPath)) return null;
  return rest + query;
}

function signedOut(out: Headers): Response {
  clearSession(out);
  return jsonError(401, "signed_out", "your session has ended; sign in again", out);
}

function refreshFailure(result: Extract<RefreshResult, { ok: false }>, out: Headers): Response {
  if (result.code === "api_unavailable") return jsonError(502, "api_unavailable", "the service is not reachable");
  return signedOut(out);
}

async function send(request: Request, path: string, token: string, session: Session): Promise<Response> {
  const config = serverConfig();
  const method = request.method.toUpperCase();
  const headers = upstreamHeaders(
    { userAgent: request.headers.get("user-agent"), forwardedFor: clientAddress(request) },
    token,
    session.deviceToken,
  );
  headers.delete("accept");
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = method !== "GET" && method !== "HEAD";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.relayTimeoutMs);
  try {
    return await fetch(config.apiBaseUrl + path, {
      method,
      headers,
      body: hasBody ? request.body : undefined,
      // a streamed request body (multipart uploads included)
      ...(hasBody ? { duplex: "half" } : {}),
      signal: controller.signal,
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } finally {
    clearTimeout(timer);
  }
}

function answer(upstream: Response, out: Headers): Response {
  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  if (upstream.headers.get("content-encoding")) headers.delete("content-length");
  if (!headers.has("cache-control")) headers.set("Cache-Control", "no-store");
  out.forEach((value, name) => {
    if (name.toLowerCase() === "set-cookie") return;
    headers.set(name, value);
  });
  for (const cookie of out.getSetCookie()) headers.append("Set-Cookie", cookie);
  const empty = upstream.status === 204 || upstream.status === 304;
  return new Response(empty ? null : upstream.body, { status: upstream.status, headers });
}

async function discard(response: Response | Request | undefined): Promise<void> {
  try {
    await response?.body?.cancel();
  } catch {
    // nothing to free
  }
}

export async function relay(request: Request): Promise<Response> {
  const refused = csrfRefusal(request);
  if (refused) return refused;
  const path = targetPath(request.url);
  if (path === null) return jsonError(404, "not_found", "no such path");
  const session = readSession(request);
  const out = new Headers();
  const ctx = { userAgent: request.headers.get("user-agent"), forwardedFor: clientAddress(request) };
  if (!session.accessToken && !session.refreshToken) return signedOut(out);

  let token = session.accessToken;
  let refreshed = false;
  if (!token && session.refreshToken) {
    const result = await refreshOnce(session.refreshToken, ctx);
    if (!result.ok) return refreshFailure(result, out);
    setTokens(out, result.tokens);
    token = result.tokens.access_token;
    refreshed = true;
  }

  const method = request.method.toUpperCase();
  const replayable = !refreshed && !!session.refreshToken;
  const spare = replayable && method !== "GET" && method !== "HEAD" ? request.clone() : undefined;
  let upstream: Response;
  try {
    upstream = await send(request, path, token as string, session);
  } catch {
    await discard(spare);
    return jsonError(502, "api_unavailable", "the service is not reachable");
  }
  if (upstream.status !== 401) {
    await discard(spare);
    return answer(upstream, out);
  }
  await discard(upstream);
  if (!replayable || !session.refreshToken) {
    await discard(spare);
    return signedOut(out);
  }
  const result = await refreshOnce(session.refreshToken, ctx);
  if (!result.ok) {
    await discard(spare);
    return refreshFailure(result, out);
  }
  setTokens(out, result.tokens);
  try {
    upstream = await send(spare ?? request, path, result.tokens.access_token, session);
  } catch {
    return jsonError(502, "api_unavailable", "the service is not reachable", out);
  }
  if (upstream.status === 401) {
    await discard(upstream);
    return signedOut(new Headers());
  }
  return answer(upstream, out);
}

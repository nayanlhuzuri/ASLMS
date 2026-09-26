/**
 * Same-origin proxy to the backend API. The browser calls /api/v1/...; this handler adds the bearer token from
 * the httpOnly cookie, streams the request and the response (uploads, PDFs, Excel exports), and refreshes the
 * session once when the backend answers 401. The browser's cookies are never forwarded to the backend.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  apiBase,
  clearSessionCookies,
  csrfOk,
  errorBody,
  forwardedHeaders,
  refreshSession,
  setSessionCookies,
  type Tokens,
} from "@/lib/server/session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Bodies up to this size are buffered so the request can be replayed after a token refresh. */
const REPLAY_LIMIT = 2 * 1024 * 1024;

const REQUEST_HEADERS = ["content-type", "accept", "accept-language"];
const RESPONSE_HEADERS = ["content-type", "content-disposition", "last-modified", "etag"];

type Ctx = { params: Promise<{ path?: string[] }> };

function badSegment(s: string): boolean {
  if (s === "" || s === "." || s === "..") return true;
  if (s.includes("/") || s.includes("\\") || s.includes("\0")) return true;
  let decoded = s;
  try {
    decoded = decodeURIComponent(s);
  } catch {
    return true;
  }
  return decoded === "." || decoded === ".." || decoded.includes("/") || decoded.includes("\\");
}

function json(status: number, error: string, message: string): NextResponse {
  const res = NextResponse.json(errorBody(error, message), { status });
  res.headers.set("cache-control", "no-store");
  return res;
}

async function handle(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  const { path = [] } = await ctx.params;
  if (path.length === 0 || path.some(badSegment)) return json(400, "bad_request", "Invalid path.");
  // Token-issuing endpoints are reached only through /api/auth/*, which keeps the tokens in cookies.
  if (path[0] === "auth") return json(404, "not_found", "Not found.");
  if (!csrfOk(req)) return json(403, "forbidden", "Request refused.");

  const target = `${apiBase()}/api/v1/${path.map((s) => encodeURIComponent(s)).join("/")}${req.nextUrl.search}`;
  const fwd = forwardedHeaders(req);
  const refreshToken = req.cookies.get(REFRESH_COOKIE)?.value;
  let accessToken = req.cookies.get(ACCESS_COOKIE)?.value;
  let renewed: Tokens | null = null;

  if (!refreshToken && !accessToken) return json(401, "unauthorized", "Sign in required.");

  // The access cookie expires with the token; renew before calling rather than after a 401.
  if (!accessToken && refreshToken) {
    const r = await refreshSession(refreshToken, fwd);
    if (!r.ok) {
      const res = json(401, "unauthorized", "Your session has ended. Sign in again.");
      clearSessionCookies(res);
      return res;
    }
    renewed = r.tokens;
    accessToken = r.tokens.access_token;
  }

  const method = req.method.toUpperCase();
  let body: ArrayBuffer | ReadableStream<Uint8Array> | undefined;
  let replayable = true;
  if (method !== "GET" && method !== "HEAD") {
    const len = Number(req.headers.get("content-length") ?? "NaN");
    if (Number.isFinite(len) && len <= REPLAY_LIMIT) {
      const buf = await req.arrayBuffer();
      body = buf.byteLength > 0 ? buf : undefined;
    } else if (req.body) {
      body = req.body;
      replayable = false;
    }
  }

  const send = (token: string | undefined): Promise<Response> => {
    const headers = new Headers(fwd);
    for (const h of REQUEST_HEADERS) {
      const v = req.headers.get(h);
      if (v) headers.set(h, v);
    }
    if (token) headers.set("authorization", `Bearer ${token}`);
    const init: RequestInit & { duplex?: "half" } = {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    };
    if (body instanceof ReadableStream) init.duplex = "half";
    return fetch(target, init);
  };

  let upstream: Response;
  try {
    upstream = await send(accessToken);
    if (upstream.status === 401 && refreshToken && !renewed && replayable) {
      const r = await refreshSession(refreshToken, fwd);
      if (r.ok) {
        renewed = r.tokens;
        await upstream.body?.cancel();
        upstream = await send(r.tokens.access_token);
      } else {
        const res = json(401, "unauthorized", "Your session has ended. Sign in again.");
        clearSessionCookies(res);
        return res;
      }
    }
  } catch {
    return json(502, "bad_gateway", "The portal server could not reach the backend.");
  }

  const headers = new Headers();
  for (const h of RESPONSE_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  const len = upstream.headers.get("content-length");
  if (len && !upstream.headers.get("content-encoding")) headers.set("content-length", len);
  headers.set("cache-control", "no-store, private");

  const noBody = upstream.status === 204 || upstream.status === 304 || method === "HEAD";
  const res = new NextResponse(noBody ? null : upstream.body, { status: upstream.status, headers });
  if (renewed) setSessionCookies(res, renewed);
  if (upstream.status === 401 && !renewed && (replayable || !refreshToken)) clearSessionCookies(res);
  return res;
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;

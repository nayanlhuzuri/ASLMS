/**
 * Backend-for-frontend session handling. Server-side only: imported by route handlers, never by client code.
 *
 * The browser never sees a token. The access token and the refresh token live in httpOnly cookies set here;
 * route handlers read them and talk to the FastAPI backend with `Authorization: Bearer`.
 */
import { createHash } from "node:crypto";
import type { NextRequest, NextResponse } from "next/server";

export const ACCESS_COOKIE = "aslms_at";
export const REFRESH_COOKIE = "aslms_rt";
const REFRESH_MAX_AGE = 14 * 24 * 60 * 60;

export function apiBase(): string {
  return (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
}

function secureCookies(): boolean {
  const flag = process.env.COOKIE_SECURE;
  if (flag === "false") return false;
  if (flag === "true") return true;
  return process.env.NODE_ENV === "production";
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in: number;
}

export function setSessionCookies(res: NextResponse, tokens: Tokens): void {
  const base = { httpOnly: true, secure: secureCookies(), sameSite: "lax" as const, path: "/" };
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...base,
    maxAge: Math.max(30, Math.floor(tokens.expires_in) - 15),
  });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, { ...base, maxAge: REFRESH_MAX_AGE });
}

export function clearSessionCookies(res: NextResponse): void {
  const base = { httpOnly: true, secure: secureCookies(), sameSite: "lax" as const, path: "/", maxAge: 0 };
  res.cookies.set(ACCESS_COOKIE, "", base);
  res.cookies.set(REFRESH_COOKIE, "", base);
}

/** Client address and agent, passed on so the backend's audit rows record the real caller. */
export function forwardedHeaders(req: NextRequest): Record<string, string> {
  const out: Record<string, string> = {};
  const fwd = req.headers.get("x-forwarded-for");
  const real = req.headers.get("x-real-ip");
  if (fwd) out["x-forwarded-for"] = fwd;
  else if (real) out["x-forwarded-for"] = real;
  const ua = req.headers.get("user-agent");
  if (ua) out["user-agent"] = ua;
  return out;
}

/**
 * Mutating requests must carry `X-Requested-With: aslms` (set by the portal's fetch client; a cross-site form
 * cannot set it) and, when the browser sends an Origin, it must be this site. Together with SameSite=Lax
 * cookies this closes cross-site request forgery.
 */
export function csrfOk(req: NextRequest): boolean {
  const method = req.method.toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return true;
  if (req.headers.get("x-requested-with") !== "aslms") return false;
  const origin = req.headers.get("origin");
  if (!origin) return true;
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * The backend rotates refresh tokens and treats the reuse of a rotated token as theft (it ends every session
 * of the user). Several browser requests can arrive together with the same expired access token, so
 * concurrent refreshes that present the same refresh token share one backend call, and the result is kept
 * for a short while for requests that were already in flight.
 */
type RefreshResult = { ok: true; tokens: Tokens } | { ok: false };
const inflight = new Map<string, { at: number; promise: Promise<RefreshResult> }>();
const SHARE_MS = 60_000;

function keyOf(refreshToken: string): string {
  return createHash("sha256").update(refreshToken).digest("hex");
}

export function refreshSession(refreshToken: string, extra: Record<string, string>): Promise<RefreshResult> {
  const now = Date.now();
  for (const [k, v] of inflight) if (now - v.at > SHARE_MS) inflight.delete(k);
  const key = keyOf(refreshToken);
  const hit = inflight.get(key);
  if (hit) return hit.promise;
  const promise = (async (): Promise<RefreshResult> => {
    try {
      const res = await fetch(`${apiBase()}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json", ...extra },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (!res.ok) return { ok: false };
      return { ok: true, tokens: (await res.json()) as Tokens };
    } catch {
      return { ok: false };
    }
  })();
  inflight.set(key, { at: now, promise });
  return promise;
}

/** A JSON error body in the backend's shape, for errors raised by the BFF itself. */
export function errorBody(error: string, message: string, details: Record<string, unknown> = {}) {
  return { error, message, details };
}

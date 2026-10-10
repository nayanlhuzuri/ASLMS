/**
 * The session cookies (design portal-shell, decision 3). Tokens live only in httpOnly cookies set by the web
 * server; browser JavaScript never sees them. `aslms_device` survives sign-out so the device is known next time.
 */
import { serverConfig } from "./config";

export const COOKIE = {
  access: "aslms_at",
  refresh: "aslms_rt",
  device: "aslms_device",
  challenge: "aslms_challenge",
} as const;

export const DEVICE_MAX_AGE = 400 * 24 * 60 * 60;
export const CHALLENGE_MAX_AGE = 15 * 60;
export const CHALLENGE_PATH = "/api/session";
const ACCESS_MARGIN_SECONDS = 30;

export interface Session {
  accessToken?: string;
  refreshToken?: string;
  deviceToken?: string;
  challengeId?: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export function parseCookies(header: string | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const name = part.slice(0, i).trim();
    if (!name || name in out) continue;
    const raw = part.slice(i + 1).trim();
    try {
      out[name] = decodeURIComponent(raw);
    } catch {
      out[name] = raw;
    }
  }
  return out;
}

export function readSession(request: Request): Session {
  const c = parseCookies(request.headers.get("cookie"));
  return {
    accessToken: c[COOKIE.access] || undefined,
    refreshToken: c[COOKIE.refresh] || undefined,
    deviceToken: c[COOKIE.device] || undefined,
    challengeId: c[COOKIE.challenge] || undefined,
  };
}

export interface CookieOptions {
  maxAge: number;
  path?: string;
}

export function serializeCookie(name: string, value: string, options: CookieOptions): string {
  const parts = [
    `${name}=${encodeURIComponent(value)}`,
    `Path=${options.path ?? "/"}`,
    `Max-Age=${Math.max(0, Math.floor(options.maxAge))}`,
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (options.maxAge <= 0) parts.push("Expires=Thu, 01 Jan 1970 00:00:00 GMT");
  if (serverConfig().cookieSecure) parts.push("Secure");
  return parts.join("; ");
}

function append(headers: Headers, name: string, value: string, options: CookieOptions): void {
  headers.append("Set-Cookie", serializeCookie(name, value, options));
}

/** The token pair: the access cookie ends 30 s before the token, the refresh cookie after the refresh days. */
export function setTokens(headers: Headers, tokens: TokenPair): void {
  append(headers, COOKIE.access, tokens.access_token, {
    maxAge: Math.max(1, tokens.expires_in - ACCESS_MARGIN_SECONDS),
  });
  append(headers, COOKIE.refresh, tokens.refresh_token, {
    maxAge: serverConfig().refreshTokenDays * 24 * 60 * 60,
  });
}

export function setDevice(headers: Headers, deviceToken: string): void {
  append(headers, COOKIE.device, deviceToken, { maxAge: DEVICE_MAX_AGE });
}

export function setChallenge(headers: Headers, challengeId: string): void {
  append(headers, COOKIE.challenge, challengeId, { maxAge: CHALLENGE_MAX_AGE, path: CHALLENGE_PATH });
}

export function clearChallenge(headers: Headers): void {
  append(headers, COOKIE.challenge, "", { maxAge: 0, path: CHALLENGE_PATH });
}

/** Every session cookie but the device cookie. */
export function clearSession(headers: Headers): void {
  append(headers, COOKIE.access, "", { maxAge: 0 });
  append(headers, COOKIE.refresh, "", { maxAge: 0 });
  clearChallenge(headers);
}

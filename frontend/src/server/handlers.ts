/**
 * The session route handlers `/api/session/*` (design portal-shell, "API"): each calls the named API endpoint,
 * keeps the challenge id and the tokens in httpOnly cookies and returns the API's step data without them. Every
 * one is a POST and passes the cross-site check first.
 */
import { ApiUnavailable, callApi, clientContext, errorCode, type ApiAnswer } from "./api";
import { csrfRefusal } from "./csrf";
import { refreshOnce } from "./refresh";
import { json, jsonError } from "./respond";
import {
  clearChallenge,
  clearSession,
  readSession,
  setChallenge,
  setDevice,
  setTokens,
  type TokenPair,
} from "./session";

const SECRET_KEYS = new Set(["access_token", "refresh_token", "device_token", "challenge_id", "token_type"]);

/** A copy of an API body without tokens or the challenge id (top level and under `detail`). */
export function scrub(data: unknown): unknown {
  if (!data || typeof data !== "object" || Array.isArray(data)) return data;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (SECRET_KEYS.has(key)) continue;
    out[key] = key === "detail" ? scrub(value) : value;
  }
  return out;
}

function passError(answer: ApiAnswer, headers = new Headers()): Response {
  const retry = answer.headers.get("retry-after");
  if (retry) headers.set("Retry-After", retry);
  const body = scrub(answer.data) ?? { detail: { code: "error", message: "the request failed" } };
  return json(answer.status, body, headers);
}

function unavailable(): Response {
  return jsonError(502, "api_unavailable", "the service is not reachable");
}

async function readBody(request: Request): Promise<Record<string, unknown>> {
  try {
    const body: unknown = await request.json();
    return body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** A short label for the device list, from the user agent ("Chrome on Windows"). */
export function deviceLabel(userAgent: string | null): string | undefined {
  if (!userAgent) return undefined;
  let browser = "Browser";
  if (/Edg\//.test(userAgent)) browser = "Edge";
  else if (/Firefox\//.test(userAgent)) browser = "Firefox";
  else if (/Chrome\//.test(userAgent)) browser = "Chrome";
  else if (/Safari\//.test(userAgent)) browser = "Safari";
  let os = "";
  if (/Windows/.test(userAgent)) os = "Windows";
  else if (/Android/.test(userAgent)) os = "Android";
  else if (/iPhone|iPad|iOS/.test(userAgent)) os = "iOS";
  else if (/Mac OS X|Macintosh/.test(userAgent)) os = "macOS";
  else if (/Linux/.test(userAgent)) os = "Linux";
  return os ? `${browser} on ${os}` : browser;
}

async function guarded(request: Request, run: () => Promise<Response>): Promise<Response> {
  const refused = csrfRefusal(request);
  if (refused) return refused;
  try {
    return await run();
  } catch (error) {
    if (error instanceof ApiUnavailable) return unavailable();
    throw error;
  }
}

export function login(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const body = await readBody(request);
    const session = readSession(request);
    const ctx = clientContext(request);
    const answer = await callApi({
      method: "POST",
      path: "/auth/login",
      body: {
        email: text(body.email),
        password: text(body.password),
        device_token: session.deviceToken,
        device_label: deviceLabel(ctx.userAgent ?? null),
      },
      ...ctx,
    });
    if (answer.status !== 200) return passError(answer);
    const data = answer.data as { challenge_id: string };
    const headers = new Headers();
    setChallenge(headers, data.challenge_id);
    return json(200, scrub(data), headers);
  });
}

export function verify(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const body = await readBody(request);
    const session = readSession(request);
    if (!session.challengeId) return jsonError(401, "otp_expired", "the code has expired; sign in again");
    const ctx = clientContext(request);
    const answer = await callApi({
      method: "POST",
      path: "/auth/otp/verify",
      body: {
        challenge_id: session.challengeId,
        code: text(body.code),
        device_token: session.deviceToken,
        device_label: deviceLabel(ctx.userAgent ?? null),
      },
      ...ctx,
    });
    if (answer.status !== 200) {
      const headers = new Headers();
      if (errorCode(answer.data) === "otp_expired") clearChallenge(headers);
      return passError(answer, headers);
    }
    const data = answer.data as TokenPair & { device_token?: string | null; next_step?: string; user?: unknown };
    const headers = new Headers();
    setTokens(headers, data);
    if (data.device_token) setDevice(headers, data.device_token);
    clearChallenge(headers);
    return json(200, { next_step: data.next_step ?? "ready", user: data.user }, headers);
  });
}

export function resend(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const session = readSession(request);
    if (!session.challengeId) return jsonError(401, "otp_expired", "the code has expired; start again");
    const answer = await callApi({
      method: "POST",
      path: "/auth/otp/resend",
      body: { challenge_id: session.challengeId },
      ...clientContext(request),
    });
    if (answer.status !== 200 && answer.status !== 202) return passError(answer);
    const data = answer.data as { challenge_id?: string };
    const headers = new Headers();
    if (data.challenge_id) setChallenge(headers, data.challenge_id);
    return json(answer.status, scrub(data), headers);
  });
}

export function resetRequest(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const body = await readBody(request);
    const answer = await callApi({
      method: "POST",
      path: "/auth/password-reset/request",
      body: { email: text(body.email) },
      ...clientContext(request),
    });
    if (answer.status !== 202) return passError(answer);
    const data = answer.data as { challenge_id: string };
    const headers = new Headers();
    setChallenge(headers, data.challenge_id);
    return json(202, scrub(data), headers);
  });
}

export function resetConfirm(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const body = await readBody(request);
    const session = readSession(request);
    if (!session.challengeId) return jsonError(401, "otp_expired", "the code has expired; start again");
    const answer = await callApi({
      method: "POST",
      path: "/auth/password-reset/confirm",
      body: { challenge_id: session.challengeId, code: text(body.code), new_password: text(body.new_password) },
      ...clientContext(request),
    });
    if (answer.status !== 204) return passError(answer);
    const headers = new Headers({ "Cache-Control": "no-store" });
    clearSession(headers);
    return new Response(null, { status: 204, headers });
  });
}

interface Access {
  token?: string;
  refreshToken?: string;
  failure?: Response;
}

/** The access token of the request, refreshing (single-flight) when only the refresh cookie is left. */
async function accessToken(request: Request, headers: Headers): Promise<Access> {
  const session = readSession(request);
  if (session.accessToken) return { token: session.accessToken, refreshToken: session.refreshToken };
  if (!session.refreshToken) return {};
  const result = await refreshOnce(session.refreshToken, clientContext(request));
  if (!result.ok) {
    if (result.code === "api_unavailable") return { failure: unavailable() };
    return {};
  }
  setTokens(headers, result.tokens);
  return { token: result.tokens.access_token, refreshToken: result.tokens.refresh_token };
}

function signedOut(): Response {
  const headers = new Headers();
  clearSession(headers);
  return jsonError(401, "signed_out", "your session has ended; sign in again", headers);
}

export function password(request: Request): Promise<Response> {
  return guarded(request, async () => {
    const body = await readBody(request);
    const headers = new Headers();
    const { token, failure } = await accessToken(request, headers);
    if (failure) return failure;
    if (!token) return signedOut();
    const session = readSession(request);
    const answer = await callApi({
      method: "POST",
      path: "/me/password",
      token,
      body: {
        current_password: text(body.current_password),
        new_password: text(body.new_password),
        device_token: session.deviceToken,
      },
      ...clientContext(request),
    });
    if (answer.status === 200) {
      const data = answer.data as TokenPair & { next_step?: string };
      const fresh = new Headers();
      setTokens(fresh, data);
      return json(200, { next_step: data.next_step ?? "ready" }, fresh);
    }
    if (answer.status === 401 && errorCode(answer.data) !== "wrong_password") return signedOut();
    return passError(answer, headers);
  });
}

export function logout(request: Request): Promise<Response> {
  return guarded(request, async () => {
    try {
      const { token, refreshToken } = await accessToken(request, new Headers());
      if (token && refreshToken) {
        await callApi({
          method: "POST",
          path: "/auth/logout",
          token,
          body: { refresh_token: refreshToken },
          ...clientContext(request),
        });
      }
    } catch {
      // the cookies are cleared whatever the API answers
    }
    const headers = new Headers({ "Cache-Control": "no-store" });
    clearSession(headers);
    return new Response(null, { status: 204, headers });
  });
}

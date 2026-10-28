/**
 * The portal's one fetch wrapper (design portal-shell, decisions 5, 9 and 11). Every call goes to the web server:
 * `/api/backend/…` (the relay) or `/api/session/…`. It sets `X-ASLMS-Request`, turns the API's three error shapes
 * into `ApiError {status, code, message, extra}`, sends the browser to the welcome pages on the server's
 * first-sign-in codes, and on `signed_out` clears the query cache and goes to `/login?next=…`. On the session ends
 * `session_idle` and `session_limit` (design session-timeout, decision 19) it does the same with `reason=idle` or
 * `reason=limit`, and tells every other tab through the shared session clock.
 */
import { sessionStore, type OutReason } from "@/lib/session/store";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

export interface ClientHooks {
  navigate: (url: string) => void;
  clearCache: () => void;
  currentPath: () => string;
}

const defaultHooks: ClientHooks = {
  navigate: (url) => window.location.assign(url),
  clearCache: () => undefined,
  currentPath: () => window.location.pathname + window.location.search,
};

let hooks: ClientHooks = { ...defaultHooks };

export function setClientHooks(next: Partial<ClientHooks>): void {
  hooks = { ...hooks, ...next };
}

export function resetClientHooks(): void {
  hooks = { ...defaultHooks };
}

const STATUS_CODES: Record<number, string> = {
  400: "bad_request",
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  409: "conflict",
  413: "too_large",
  422: "validation",
  429: "too_many",
  502: "api_unavailable",
  503: "unavailable",
};

interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

/** `{detail: {code, message, …}}`, `{detail: "text"}` or FastAPI's 422 `{detail: [{loc, msg}]}`. */
export function parseError(status: number, body: unknown): ApiError {
  const fallback = STATUS_CODES[status] ?? `http_${status}`;
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return new ApiError(status, fallback, detail);
  if (Array.isArray(detail)) {
    const fields = (detail as ValidationItem[]).map((d) => ({
      field: (d.loc ?? []).filter((x) => x !== "body" && x !== "query").join("."),
      message: d.msg ?? "invalid",
    }));
    const message = fields.map((f) => (f.field ? `${f.field}: ${f.message}` : f.message)).join("; ");
    return new ApiError(status, "validation", message || "invalid input", { fields });
  }
  if (detail && typeof detail === "object") {
    const { code, message, ...extra } = detail as Record<string, unknown>;
    return new ApiError(
      status,
      typeof code === "string" ? code : fallback,
      typeof message === "string" ? message : "the request failed",
      extra,
    );
  }
  return new ApiError(status, fallback, "the request failed");
}

export const GATE_PAGES: Record<string, string> = {
  password_change_required: "/welcome/password",
  profile_confirmation_required: "/welcome/profile",
};

/** The 401 codes that end the session in the browser, with the reason the sign-in page explains. */
export const SIGNED_OUT_CODES: Record<string, OutReason> = {
  session_idle: "idle",
  session_limit: "limit",
  signed_out: null,
  session_ended: null,
};

/** `/login`, with `reason` when there is one and `next` = the current page unless it is the start or sign-in page. */
export function loginAddress(reason: OutReason = null, here: string = hooks.currentPath()): string {
  const params = new URLSearchParams();
  if (reason) params.set("reason", reason);
  if (here && here !== "/" && !here.startsWith("/login")) params.set("next", here);
  const qs = params.toString();
  return qs ? `/login?${qs}` : "/login";
}

/**
 * Leaves for the sign-in page: the cache cleared, and unless `broadcast` is false (a tab following another), the
 * reason written to the shared clock so every other tab of the browser leaves too.
 */
export function signedOut(reason: OutReason = null, { broadcast = true }: { broadcast?: boolean } = {}): void {
  if (broadcast) sessionStore().setOut(reason);
  hooks.clearCache();
  hooks.navigate(loginAddress(reason));
}

async function handle(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
  }
  if (response.ok) return body;
  const error = parseError(response.status, body);
  const gate = GATE_PAGES[error.code];
  if (response.status === 401 && error.code in SIGNED_OUT_CODES) signedOut(SIGNED_OUT_CODES[error.code] ?? null);
  else if (response.status === 403 && gate) hooks.navigate(gate);
  throw error;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface CallOptions {
  method?: string;
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function send(url: string, options: CallOptions): Promise<Response> {
  const headers: Record<string, string> = { "X-ASLMS-Request": "1", Accept: "application/json" };
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) body = options.body;
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  try {
    return await fetch(url, {
      method: options.method ?? (options.body !== undefined ? "POST" : "GET"),
      headers,
      body,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "the portal could not be reached");
  }
}

/** A call through the relay: `api("/me")` → `GET /api/backend/me`. */
export async function api<T>(path: string, options: CallOptions = {}): Promise<T> {
  const response = await send("/api/backend" + withQuery(path, options.query), options);
  return (await handle(response)) as T;
}

/**
 * Asks for a file through the relay and stops reading once the answer's head arrives: resolves when the file is there
 * and throws the API's error otherwise, so a screen can show a `no_pdf` or `file_missing` message before the browser's
 * own viewer opens the address (the View Cause List modal, design portal-ui-polish-2, decision 25).
 */
export async function probeFile(path: string, options: CallOptions = {}): Promise<void> {
  const controller = new AbortController();
  const response = await send("/api/backend" + withQuery(path, options.query), { signal: controller.signal });
  if (response.ok) {
    controller.abort();
    return;
  }
  await handle(response);
}

/** A list call that also returns the `X-Total-Count` header. */
export async function apiPage<T>(path: string, options: CallOptions = {}): Promise<{ items: T; total: number }> {
  const response = await send("/api/backend" + withQuery(path, options.query), options);
  const items = (await handle(response)) as T;
  const header = response.headers.get("x-total-count");
  const total = header === null ? NaN : Number(header);
  return { items, total: Number.isFinite(total) ? total : Array.isArray(items) ? items.length : 0 };
}

/** A session step: `session("login", {...})` → `POST /api/session/login`. */
export async function session<T>(step: string, body: unknown = {}): Promise<T> {
  const response = await send(`/api/session/${step}`, { method: "POST", body });
  return (await handle(response)) as T;
}

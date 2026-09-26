/**
 * Browser API client. Calls the same-origin proxy (/api/v1/...), which adds the bearer token from the httpOnly
 * cookie. Errors carry the backend's {error, message, details} body.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}${path.includes("?") ? "&" : "?"}${s}` : path;
}

/** URL of an API resource for links (downloads, exports), relative to the portal. */
export function apiUrl(path: string, query?: Query): string {
  return withQuery(`/api/v1${path}`, query);
}

function messageFor(status: number): string {
  if (status === 403) return "You do not have permission to do this.";
  if (status === 404) return "Not found.";
  if (status === 413) return "The file is too large.";
  if (status >= 500) return "The server could not complete the request. Try again shortly.";
  return "The request could not be completed.";
}

async function toError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = messageFor(res.status);
  let details: Record<string, unknown> = {};
  try {
    const body = (await res.json()) as { error?: unknown; message?: unknown; details?: unknown; detail?: unknown };
    if (typeof body.error === "string") code = body.error;
    if (typeof body.message === "string" && body.message) message = body.message;
    else if (typeof body.detail === "string" && body.detail) message = body.detail;
    if (body.details && typeof body.details === "object") details = body.details as Record<string, unknown>;
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, code, message, details);
}

let redirecting = false;

function toLogin(): void {
  if (typeof window === "undefined" || redirecting) return;
  redirecting = true;
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

interface Options {
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function request<T>(method: string, path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json", "x-requested-with": "aslms" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(apiUrl(path, opts.query), {
      method,
      headers,
      body,
      signal: opts.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "The portal could not be reached. Check your connection.");
  }
  if (res.status === 401) {
    toLogin();
    throw await toError(res);
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body: body ?? {}, query }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
};

/** Calls one of the portal's own /api/auth/* handlers (sign-in, OTP, password reset, sign-out). */
export async function authCall<T>(name: "login" | "verify" | "logout" | "forgot" | "reset", body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/auth/${name}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", "x-requested-with": "aslms" },
      body: JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "The portal could not be reached. Check your connection.");
  }
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}

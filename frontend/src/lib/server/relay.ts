import { NextResponse, type NextRequest } from "next/server";
import { apiBase, csrfOk, errorBody, forwardedHeaders } from "./session";

export interface Relayed {
  status: number;
  body: unknown;
}

/** POST a JSON body to a backend auth endpoint and return its status and parsed body. */
export async function postBackend(req: NextRequest, path: string, payload: unknown): Promise<Relayed> {
  try {
    const res = await fetch(`${apiBase()}/api/v1${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", ...forwardedHeaders(req) },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    let body: unknown = null;
    const text = await res.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = errorBody("bad_gateway", "The server returned an unexpected answer.");
      }
    }
    return { status: res.status, body };
  } catch {
    return { status: 502, body: errorBody("bad_gateway", "The portal server could not reach the backend.") };
  }
}

/** Read a JSON request body, or answer 400. Also enforces the CSRF header. */
export async function readJson(req: NextRequest): Promise<{ ok: true; data: Record<string, unknown> } | { ok: false; res: NextResponse }> {
  if (!csrfOk(req)) {
    return { ok: false, res: NextResponse.json(errorBody("forbidden", "Request refused."), { status: 403 }) };
  }
  try {
    const data = (await req.json()) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("not an object");
    return { ok: true, data: data as Record<string, unknown> };
  } catch {
    return { ok: false, res: NextResponse.json(errorBody("validation_error", "Invalid request."), { status: 400 }) };
  }
}

export function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export function noStore(res: NextResponse): NextResponse {
  res.headers.set("cache-control", "no-store");
  return res;
}

/** Error answers of the web server in the API's shape: `{detail: {code, message}}`, never cached. */
export function jsonError(
  status: number,
  code: string,
  message: string,
  headers?: Headers,
  extra?: Record<string, unknown>,
): Response {
  const h = headers ?? new Headers();
  h.set("Content-Type", "application/json");
  h.set("Cache-Control", "no-store");
  return new Response(JSON.stringify({ detail: { ...extra, code, message } }), { status, headers: h });
}

export function json(status: number, body: unknown, headers?: Headers): Response {
  const h = headers ?? new Headers();
  h.set("Content-Type", "application/json");
  h.set("Cache-Control", "no-store");
  return new Response(JSON.stringify(body), { status, headers: h });
}

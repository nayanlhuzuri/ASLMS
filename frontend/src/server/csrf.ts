/**
 * Cross-site request protection (design portal-shell, decision 5): a non-GET request needs the header
 * `X-ASLMS-Request: 1` (set by the portal's fetch wrapper) and, when the browser sends `Origin`, the origin of
 * PORTAL_BASE_URL. No CORS header is ever sent, so a cross-site script cannot pass the preflight.
 */
import { serverConfig } from "./config";
import { jsonError } from "./respond";

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export function csrfRefusal(request: Request): Response | null {
  if (SAFE.has(request.method.toUpperCase())) return null;
  if (request.headers.get("x-aslms-request") !== "1") {
    return jsonError(403, "csrf", "the request did not come from the portal");
  }
  const origin = request.headers.get("origin");
  if (origin !== null) {
    let expected: string;
    try {
      expected = new URL(serverConfig().portalBaseUrl).origin;
    } catch {
      return jsonError(403, "csrf", "the portal address is not configured");
    }
    if (origin !== expected) return jsonError(403, "csrf", "the request came from another site");
  }
  return null;
}

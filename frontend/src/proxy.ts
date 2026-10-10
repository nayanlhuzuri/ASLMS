/**
 * The page gate and the security headers (design portal-shell, decisions 10 and 18). A page request without the
 * refresh cookie goes to `/login?next=…`; this is convenience only, the API decides every figure and action.
 * Every page gets a CSP with a per-request nonce, nosniff, a same-origin referrer and a restrictive
 * Permissions-Policy. `/api/*` is not matched (the route handlers answer for themselves).
 */
import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PAGES = new Set(["/login", "/login/code", "/forgot", "/forgot/code"]);
const REFRESH_COOKIE = "aslms_rt";

export function contentSecurityPolicy(nonce: string, dev = process.env.NODE_ENV === "development"): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join("; ");
}

export function securityHeaders(headers: Headers, csp: string): void {
  headers.set("Content-Security-Policy", csp);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "same-origin");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("X-Frame-Options", "DENY");
}

export function proxy(request: NextRequest): NextResponse {
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce);
  const { pathname, search } = request.nextUrl;
  if (!PUBLIC_PAGES.has(pathname) && !request.cookies.get(REFRESH_COOKIE)?.value) {
    const target = request.nextUrl.clone();
    target.pathname = "/login";
    target.search = pathname === "/" && !search ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    const redirect = NextResponse.redirect(target);
    securityHeaders(redirect.headers, csp);
    return redirect;
  }
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  securityHeaders(response.headers, csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api/|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};

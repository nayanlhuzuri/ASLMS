// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, contentSecurityPolicy, proxy } from "./proxy";

describe("page gate and security headers", () => {
  it("sends a page request without the refresh cookie to sign-in with next", () => {
    const r = proxy(new NextRequest("http://localhost:3000/admin/tickets/TKT-EDU-2026-0001?x=1"));
    expect(r.status).toBe(307);
    expect(r.headers.get("location")).toBe(
      "http://localhost:3000/login?next=%2Fadmin%2Ftickets%2FTKT-EDU-2026-0001%3Fx%3D1",
    );
    expect(r.headers.get("content-security-policy")).toContain("frame-ancestors 'none'");
  });

  it("leaves the emblem files under /brand/ out of the gate, so the sign-in page can show them", () => {
    const gated = new RegExp(`^${config.matcher[0]?.source ?? ""}$`);
    expect(gated.test("/brand/assam-emblem-lockup.png")).toBe(false);
    expect(gated.test("/admin/tickets")).toBe(true);
    expect(gated.test("/branding-notes")).toBe(true);
  });

  it("lets the sign-in pages through and sets the headers", () => {
    const r = proxy(new NextRequest("http://localhost:3000/login"));
    expect(r.headers.get("location")).toBeNull();
    expect(r.headers.get("x-content-type-options")).toBe("nosniff");
    expect(r.headers.get("referrer-policy")).toBe("same-origin");
    expect(r.headers.get("permissions-policy")).toBe("camera=(), microphone=(), geolocation=()");
  });

  it("lets a signed-in page through with a per-request nonce", () => {
    const a = proxy(new NextRequest("http://localhost:3000/", { headers: { cookie: "aslms_rt=R" } }));
    const b = proxy(new NextRequest("http://localhost:3000/", { headers: { cookie: "aslms_rt=R" } }));
    const nonce = (h: string | null) => /'nonce-([^']+)'/.exec(h ?? "")?.[1];
    expect(a.headers.get("location")).toBeNull();
    expect(nonce(a.headers.get("content-security-policy"))).toBeTruthy();
    expect(nonce(a.headers.get("content-security-policy"))).not.toBe(nonce(b.headers.get("content-security-policy")));
  });

  it("allows no inline script without the nonce and no other origin", () => {
    const csp = contentSecurityPolicy("abc", false);
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toContain("base-uri 'self'");
  });
});

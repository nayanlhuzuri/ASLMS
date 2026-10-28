// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";

import { clearSession, readSession, setChallenge, setDevice, setTokens } from "./session";

function cookies(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of headers.getSetCookie()) out[line.split("=")[0]!] = line;
  return out;
}

afterEach(() => {
  delete process.env.COOKIE_SECURE;
});

describe("session cookies", () => {
  it("sets HttpOnly, SameSite=Lax, Secure cookies that die with the session", () => {
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 1800, session_expires_in: 43_000 });
    const c = cookies(h);
    expect(c.aslms_at).toContain("aslms_at=A");
    expect(c.aslms_at).toContain("Max-Age=1770");
    expect(c.aslms_rt).toContain("Max-Age=43000");
    for (const line of Object.values(c)) {
      expect(line).toContain("HttpOnly");
      expect(line).toContain("SameSite=Lax");
      expect(line).toContain("Secure");
      expect(line).toContain("Path=/");
    }
  });

  it("caps the access cookie at the session's end (session-timeout, decision 15)", () => {
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 1800, session_expires_in: 600 });
    const c = cookies(h);
    expect(c.aslms_rt).toContain("Max-Age=600");
    expect(c.aslms_at).toContain("Max-Age=570");
  });

  it("falls back to 12 hours without session_expires_in, and drops Secure only when COOKIE_SECURE=false", () => {
    process.env.COOKIE_SECURE = "false";
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 600 });
    const c = cookies(h);
    expect(c.aslms_rt).not.toContain("Secure");
    expect(c.aslms_rt).toContain(`Max-Age=${12 * 3600}`);
    expect(c.aslms_at).toContain("Max-Age=570");
  });

  it("gives zero-life cookies when the session has no time left (review finding 4)", () => {
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 1, session_expires_in: 0 });
    const c = cookies(h);
    expect(c.aslms_rt).toContain("Max-Age=0");
    expect(c.aslms_at).toContain("Max-Age=0");
  });

  it("reads under a second left as zero and a malformed value as missing", () => {
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 1800, session_expires_in: 0.4 });
    expect(cookies(h).aslms_rt).toContain("Max-Age=0");
    const g = new Headers();
    setTokens(g, { access_token: "A", refresh_token: "R", expires_in: 1800, session_expires_in: -5 });
    expect(cookies(g).aslms_rt).toContain(`Max-Age=${12 * 3600}`);
  });

  it("keeps the device for 400 days and the challenge for 15 minutes on /api/session", () => {
    const h = new Headers();
    setDevice(h, "D");
    setChallenge(h, "C");
    const c = cookies(h);
    expect(c.aslms_device).toContain(`Max-Age=${400 * 86400}`);
    expect(c.aslms_challenge).toContain("Max-Age=900");
    expect(c.aslms_challenge).toContain("Path=/api/session");
  });

  it("clearSession clears the tokens and the challenge but keeps the device cookie", () => {
    const h = new Headers();
    clearSession(h);
    const c = cookies(h);
    expect(Object.keys(c).sort()).toEqual(["aslms_at", "aslms_challenge", "aslms_rt"]);
    expect(c.aslms_at).toContain("Max-Age=0");
    expect(c.aslms_device).toBeUndefined();
  });

  it("reads the session from the Cookie header", () => {
    const r = new Request("http://x/", { headers: { cookie: "aslms_at=a; aslms_rt=r; aslms_device=d; other=1" } });
    expect(readSession(r)).toEqual({ accessToken: "a", refreshToken: "r", deviceToken: "d", challengeId: undefined });
  });
});

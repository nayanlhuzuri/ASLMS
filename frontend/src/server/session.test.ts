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
  delete process.env.ASLMS_REFRESH_TOKEN_DAYS;
});

describe("session cookies", () => {
  it("sets HttpOnly, SameSite=Lax, Secure cookies with the token lifetimes", () => {
    process.env.ASLMS_REFRESH_TOKEN_DAYS = "14";
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 1800 });
    const c = cookies(h);
    expect(c.aslms_at).toContain("aslms_at=A");
    expect(c.aslms_at).toContain("Max-Age=1770");
    expect(c.aslms_rt).toContain(`Max-Age=${14 * 86400}`);
    for (const line of Object.values(c)) {
      expect(line).toContain("HttpOnly");
      expect(line).toContain("SameSite=Lax");
      expect(line).toContain("Secure");
      expect(line).toContain("Path=/");
    }
  });

  it("drops Secure only when COOKIE_SECURE=false and reads the refresh days", () => {
    process.env.COOKIE_SECURE = "false";
    process.env.ASLMS_REFRESH_TOKEN_DAYS = "7";
    const h = new Headers();
    setTokens(h, { access_token: "A", refresh_token: "R", expires_in: 600 });
    const c = cookies(h);
    expect(c.aslms_rt).not.toContain("Secure");
    expect(c.aslms_rt).toContain(`Max-Age=${7 * 86400}`);
    expect(c.aslms_at).toContain("Max-Age=570");
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

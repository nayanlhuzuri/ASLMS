// @vitest-environment node
import { beforeEach, describe, expect, it } from "vitest";

import { resetRefreshMemory } from "@/server/refresh";
import { fakeApi, jsonResponse, portalRequest, setCookies } from "@/test/fakeApi";

import { POST as login } from "./login/route";
import { POST as resend } from "./resend/route";
import { POST as verify } from "./verify/route";

const USER = { id: "u1", email: "a@example.org", full_name: "A" };
const SECRETS = ["access_token", "refresh_token", "device_token", "challenge_id", "AT-1", "RT-1", "DEV-1", "CH-1"];

function expectNoSecret(text: string) {
  for (const s of SECRETS) expect(text).not.toContain(s);
}

beforeEach(() => {
  resetRefreshMemory();
});

describe("POST /api/session/login", () => {
  it("keeps the challenge in a cookie and returns the step without it", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/login", () =>
      jsonResponse(200, {
        step: "otp",
        challenge_id: "CH-1",
        purpose: "login",
        sent_to: "a***@example.org",
        expires_in: 600,
        resend_after: 120,
      }),
    );
    const r = await login(
      portalRequest("/api/session/login", {
        method: "POST",
        cookies: { aslms_device: "DEV-0" },
        headers: { "user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0" },
        body: JSON.stringify({ email: "a@example.org", password: "pw" }),
      }),
    );
    expect(r.status).toBe(200);
    const text = await r.text();
    expectNoSecret(text);
    expect(JSON.parse(text)).toMatchObject({ step: "otp", sent_to: "a***@example.org", resend_after: 120 });
    expect(setCookies(r).aslms_challenge).toContain("aslms_challenge=CH-1");
    const sent = JSON.parse(api.calls[0]!.body!);
    expect(sent).toMatchObject({ email: "a@example.org", device_token: "DEV-0", device_label: "Chrome on Windows" });
  });

  it("passes the API's refusal with Retry-After", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/login", () =>
      jsonResponse(429, { detail: { code: "locked", message: "wait", retry_after: 300 } }, { "retry-after": "300" }),
    );
    const r = await login(portalRequest("/api/session/login", { method: "POST", body: "{}" }));
    expect(r.status).toBe(429);
    expect(r.headers.get("retry-after")).toBe("300");
    expect((await r.json()).detail).toMatchObject({ code: "locked", retry_after: 300 });
  });

  it("refuses a cross-site call", async () => {
    const api = fakeApi();
    const r = await login(portalRequest("/api/session/login", { method: "POST", body: "{}", portal: false }));
    expect(r.status).toBe(403);
    expect(api.calls).toHaveLength(0);
  });

  it("answers 502 when the API is down", async () => {
    const api = fakeApi();
    api.setDown(true);
    const r = await login(portalRequest("/api/session/login", { method: "POST", body: "{}" }));
    expect(r.status).toBe(502);
  });
});

describe("POST /api/session/verify", () => {
  it("sets the three cookies, clears the challenge and returns next_step without a token", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/otp/verify", () =>
      jsonResponse(200, {
        access_token: "AT-1",
        refresh_token: "RT-1",
        token_type: "bearer",
        expires_in: 1800,
        user: USER,
        next_step: "change_password",
        device_token: "DEV-1",
      }),
    );
    const r = await verify(
      portalRequest("/api/session/verify", {
        method: "POST",
        cookies: { aslms_challenge: "CH-1" },
        body: JSON.stringify({ code: "123456" }),
      }),
    );
    expect(r.status).toBe(200);
    const text = await r.text();
    expectNoSecret(text);
    expect(JSON.parse(text)).toEqual({ next_step: "change_password", user: USER });
    const c = setCookies(r);
    expect(c.aslms_at).toContain("aslms_at=AT-1");
    expect(c.aslms_rt).toContain("aslms_rt=RT-1");
    expect(c.aslms_device).toContain("aslms_device=DEV-1");
    expect(c.aslms_challenge).toContain("Max-Age=0");
    expect(JSON.parse(api.calls[0]!.body!)).toMatchObject({ challenge_id: "CH-1", code: "123456" });
  });

  it("passes attempts_left on a wrong code and keeps the challenge", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/otp/verify", () =>
      jsonResponse(401, { detail: { code: "otp_invalid", message: "wrong", attempts_left: 4 } }),
    );
    const r = await verify(
      portalRequest("/api/session/verify", { method: "POST", cookies: { aslms_challenge: "CH-1" }, body: "{}" }),
    );
    expect(r.status).toBe(401);
    expect((await r.json()).detail.attempts_left).toBe(4);
    expect(setCookies(r).aslms_challenge).toBeUndefined();
  });

  it("answers otp_expired without a challenge cookie", async () => {
    const api = fakeApi();
    const r = await verify(portalRequest("/api/session/verify", { method: "POST", body: "{}" }));
    expect(r.status).toBe(401);
    expect((await r.json()).detail.code).toBe("otp_expired");
    expect(api.calls).toHaveLength(0);
  });
});

describe("POST /api/session/resend", () => {
  it("replaces the challenge cookie and hides the id", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/otp/resend", () =>
      jsonResponse(200, { step: "otp", challenge_id: "CH-2", purpose: "login", sent_to: "a***", expires_in: 600, resend_after: 120 }),
    );
    const r = await resend(
      portalRequest("/api/session/resend", { method: "POST", cookies: { aslms_challenge: "CH-1" }, body: "{}" }),
    );
    expect(r.status).toBe(200);
    expect(await r.text()).not.toContain("CH-2");
    expect(setCookies(r).aslms_challenge).toContain("aslms_challenge=CH-2");
  });
});

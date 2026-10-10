// @vitest-environment node
import { beforeEach, describe, expect, it } from "vitest";

import { resetRefreshMemory } from "@/server/refresh";
import { fakeApi, jsonResponse, portalRequest, setCookies } from "@/test/fakeApi";

import { POST as logout } from "./logout/route";
import { POST as password } from "./password/route";
import { POST as resetConfirm } from "./reset/confirm/route";
import { POST as resetRequest } from "./reset/request/route";

beforeEach(() => {
  resetRefreshMemory();
});

describe("password reset", () => {
  it("the request is a neutral 202 with the challenge in a cookie", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/password-reset/request", () =>
      jsonResponse(202, { challenge_id: "CH-9", expires_in: 600, resend_after: 120 }),
    );
    const r = await resetRequest(
      portalRequest("/api/session/reset/request", { method: "POST", body: JSON.stringify({ email: "x@example.org" }) }),
    );
    expect(r.status).toBe(202);
    const text = await r.text();
    expect(text).not.toContain("CH-9");
    expect(JSON.parse(text)).toEqual({ expires_in: 600, resend_after: 120 });
    expect(setCookies(r).aslms_challenge).toContain("aslms_challenge=CH-9");
  });

  it("the confirmation clears the challenge and the session cookies but keeps the device", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/password-reset/confirm", () => new Response(null, { status: 204 }));
    const r = await resetConfirm(
      portalRequest("/api/session/reset/confirm", {
        method: "POST",
        cookies: { aslms_challenge: "CH-9", aslms_device: "D" },
        body: JSON.stringify({ code: "123456", new_password: "a-new-password-1" }),
      }),
    );
    expect(r.status).toBe(204);
    const c = setCookies(r);
    expect(c.aslms_challenge).toContain("Max-Age=0");
    expect(c.aslms_rt).toContain("Max-Age=0");
    expect(c.aslms_device).toBeUndefined();
    expect(JSON.parse(api.calls[0]!.body!)).toEqual({
      challenge_id: "CH-9",
      code: "123456",
      new_password: "a-new-password-1",
    });
  });
});

describe("password change", () => {
  it("replaces the token cookies and returns only next_step", async () => {
    const api = fakeApi();
    api.on("POST", "/me/password", (call) => {
      expect(call.headers.get("authorization")).toBe("Bearer A1");
      return jsonResponse(200, { access_token: "A2", refresh_token: "R2", expires_in: 1800, next_step: "confirm_profile" });
    });
    const r = await password(
      portalRequest("/api/session/password", {
        method: "POST",
        cookies: { aslms_at: "A1", aslms_rt: "R1" },
        body: JSON.stringify({ current_password: "old", new_password: "new-password-1" }),
      }),
    );
    expect(r.status).toBe(200);
    const text = await r.text();
    expect(text).not.toContain("A2");
    expect(JSON.parse(text)).toEqual({ next_step: "confirm_profile" });
    expect(setCookies(r).aslms_rt).toContain("aslms_rt=R2");
  });

  it("passes wrong_password without signing out", async () => {
    const api = fakeApi();
    api.on("POST", "/me/password", () => jsonResponse(401, { detail: { code: "wrong_password", message: "no" } }));
    const r = await password(
      portalRequest("/api/session/password", { method: "POST", cookies: { aslms_at: "A1", aslms_rt: "R1" }, body: "{}" }),
    );
    expect(r.status).toBe(401);
    expect((await r.json()).detail.code).toBe("wrong_password");
    expect(r.headers.getSetCookie()).toEqual([]);
  });
});

describe("logout", () => {
  it("revokes the refresh token at the API and clears the cookies, keeping the device", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/logout", () => new Response(null, { status: 204 }));
    const r = await logout(
      portalRequest("/api/session/logout", {
        method: "POST",
        cookies: { aslms_at: "A1", aslms_rt: "R1", aslms_device: "D" },
      }),
    );
    expect(r.status).toBe(204);
    expect(JSON.parse(api.calls[0]!.body!)).toEqual({ refresh_token: "R1" });
    const c = setCookies(r);
    expect(c.aslms_at).toContain("Max-Age=0");
    expect(c.aslms_rt).toContain("Max-Age=0");
    expect(c.aslms_device).toBeUndefined();
  });

  it("refreshes first when the access token has expired", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () => jsonResponse(200, { access_token: "A2", refresh_token: "R2", expires_in: 1800 }));
    api.on("POST", "/auth/logout", () => new Response(null, { status: 204 }));
    const r = await logout(portalRequest("/api/session/logout", { method: "POST", cookies: { aslms_rt: "R1" } }));
    expect(r.status).toBe(204);
    expect(api.calls.map((c) => c.path)).toEqual(["/auth/refresh", "/auth/logout"]);
    expect(JSON.parse(api.calls[1]!.body!)).toEqual({ refresh_token: "R2" });
    expect(api.calls[1]!.headers.get("authorization")).toBe("Bearer A2");
  });

  it("clears the cookies when the API is down", async () => {
    const api = fakeApi();
    api.setDown(true);
    const r = await logout(
      portalRequest("/api/session/logout", { method: "POST", cookies: { aslms_at: "A1", aslms_rt: "R1" } }),
    );
    expect(r.status).toBe(204);
    expect(setCookies(r).aslms_rt).toContain("Max-Age=0");
  });
});

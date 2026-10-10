// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeApi, jsonResponse, portalRequest, setCookies } from "@/test/fakeApi";

import { refreshOnce, REMEMBER_MS, rememberedCount, resetRefreshMemory } from "./refresh";
import { relay } from "./relay";

const NEW_PAIR = { access_token: "A2", refresh_token: "R2", expires_in: 1800, token_type: "bearer" };

beforeEach(() => {
  resetRefreshMemory();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("single-flight refresh", () => {
  it("two concurrent requests with an expired access token make one /auth/refresh", async () => {
    const api = fakeApi();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    api.on("POST", "/auth/refresh", async () => {
      await gate;
      return jsonResponse(200, NEW_PAIR);
    });
    api.on("GET", "/dashboard/me", (call) => jsonResponse(200, { auth: call.headers.get("authorization") }));
    api.on("GET", "/dashboard/state", (call) => jsonResponse(200, { auth: call.headers.get("authorization") }));
    const one = relay(portalRequest("/api/backend/dashboard/me", { cookies: { aslms_rt: "R1" } }));
    const two = relay(portalRequest("/api/backend/dashboard/state", { cookies: { aslms_rt: "R1" } }));
    release();
    const [a, b] = await Promise.all([one, two]);
    expect(api.calls.filter((c) => c.path === "/auth/refresh")).toHaveLength(1);
    expect(await a.json()).toEqual({ auth: "Bearer A2" });
    expect(await b.json()).toEqual({ auth: "Bearer A2" });
    expect(setCookies(a).aslms_rt).toContain("aslms_rt=R2");
    expect(setCookies(b).aslms_rt).toContain("aslms_rt=R2");
  });

  it("a request with the old refresh token inside 30 s gets the remembered pair without a call", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () => jsonResponse(200, NEW_PAIR));
    const first = await refreshOnce("R1");
    vi.setSystemTime(Date.now() + REMEMBER_MS - 1000);
    const again = await refreshOnce("R1");
    expect(first).toEqual(again);
    expect(first.ok).toBe(true);
    expect(api.calls).toHaveLength(1);
  });

  it("after 30 s the entry is gone", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () => jsonResponse(200, NEW_PAIR));
    await refreshOnce("R1");
    expect(rememberedCount()).toBe(1);
    vi.setSystemTime(Date.now() + REMEMBER_MS + 1);
    expect(rememberedCount()).toBe(0);
    await refreshOnce("R1");
    expect(api.calls).toHaveLength(2);
  });

  it.each(["session_ended", "refresh_invalid"])("%s clears the cookies and gives 401 signed_out", async (code) => {
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () => jsonResponse(401, { detail: { code, message: "no" } }));
    const r = await relay(portalRequest("/api/backend/me", { cookies: { aslms_rt: "R1", aslms_device: "D" } }));
    expect(r.status).toBe(401);
    expect((await r.json()).detail.code).toBe("signed_out");
    const c = setCookies(r);
    expect(c.aslms_at).toContain("Max-Age=0");
    expect(c.aslms_rt).toContain("Max-Age=0");
    expect(c.aslms_device).toBeUndefined();
    expect(api.calls.map((x) => x.path)).toEqual(["/auth/refresh"]);
  });

  it("an unreachable API is not remembered and does not sign out", async () => {
    const api = fakeApi();
    api.setDown(true);
    const r = await relay(portalRequest("/api/backend/me", { cookies: { aslms_rt: "R1" } }));
    expect(r.status).toBe(502);
    expect(r.headers.getSetCookie()).toEqual([]);
    expect(rememberedCount()).toBe(0);
  });
});

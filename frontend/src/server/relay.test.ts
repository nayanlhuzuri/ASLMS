// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fakeApi, jsonResponse, portalRequest, setCookies } from "@/test/fakeApi";

import { resetRefreshMemory } from "./refresh";
import { relay, targetPath } from "./relay";

const SIGNED_IN = { aslms_at: "A1", aslms_rt: "R1", aslms_device: "D1" };
const ORIGIN = "http://localhost:3000";

beforeEach(() => {
  resetRefreshMemory();
});

afterEach(() => {
  delete process.env.RELAY_TIMEOUT_SECONDS;
});

describe("relay", () => {
  it("adds Authorization and the device token from the cookies, never the browser's", async () => {
    const api = fakeApi();
    api.on("GET", "/me", () => jsonResponse(200, { ok: true }));
    const r = await relay(
      portalRequest("/api/backend/me?x=1", {
        cookies: SIGNED_IN,
        headers: {
          authorization: "Bearer forged",
          "x-device-token": "forged-device",
          "x-forwarded-for": "203.0.113.9, 10.0.0.1",
          "user-agent": "UA/1",
          accept: "application/json",
          "x-other": "dropped",
        },
      }),
    );
    expect(r.status).toBe(200);
    const call = api.calls[0]!;
    expect(call.url).toBe("http://api.test/me?x=1");
    expect(call.headers.get("authorization")).toBe("Bearer A1");
    expect(call.headers.get("x-device-token")).toBe("D1");
    expect(call.headers.get("cookie")).toBeNull();
    expect(call.headers.get("x-other")).toBeNull();
    expect(call.headers.get("user-agent")).toBe("UA/1");
    expect(call.headers.get("accept")).toBe("application/json");
    expect(call.headers.get("x-forwarded-for")).toBe("203.0.113.9");
  });

  it("does not forward a device token the browser sends without the cookie", async () => {
    const api = fakeApi();
    api.on("GET", "/me", () => jsonResponse(200, {}));
    await relay(portalRequest("/api/backend/me", { cookies: { aslms_at: "A1" }, headers: { "x-device-token": "x" } }));
    expect(api.calls[0]!.headers.get("x-device-token")).toBeNull();
  });

  it("never returns Set-Cookie and keeps only the allowed response headers", async () => {
    const api = fakeApi();
    api.on(
      "GET",
      "/admin/users",
      () =>
        new Response("[]", {
          status: 200,
          headers: {
            "content-type": "application/json",
            "set-cookie": "evil=1",
            "x-total-count": "42",
            "content-disposition": 'attachment; filename="a.pdf"',
            "retry-after": "5",
            server: "uvicorn",
            "x-internal": "secret",
          },
        }),
    );
    const r = await relay(portalRequest("/api/backend/admin/users", { cookies: SIGNED_IN }));
    expect(r.headers.getSetCookie()).toEqual([]);
    expect(r.headers.get("x-total-count")).toBe("42");
    expect(r.headers.get("content-disposition")).toContain("a.pdf");
    expect(r.headers.get("retry-after")).toBe("5");
    expect(r.headers.get("content-type")).toBe("application/json");
    expect(r.headers.get("server")).toBeNull();
    expect(r.headers.get("x-internal")).toBeNull();
    expect(r.headers.get("cache-control")).toBe("no-store");
  });

  it("passes the API's nosniff and sandbox headers of a document viewed inline", async () => {
    const api = fakeApi();
    api.on(
      "GET",
      "/documents/d-1/file",
      () =>
        new Response("%PDF-1.7", {
          status: 200,
          headers: {
            "content-type": "application/pdf",
            "content-disposition": 'inline; filename="order.pdf"',
            "x-content-type-options": "nosniff",
            "content-security-policy": "sandbox",
            "x-frame-options": "DENY",
            server: "uvicorn",
          },
        }),
    );
    const r = await relay(portalRequest("/api/backend/documents/d-1/file?disposition=inline", { cookies: SIGNED_IN }));
    expect(r.status).toBe(200);
    expect(r.headers.get("x-content-type-options")).toBe("nosniff");
    expect(r.headers.get("content-security-policy")).toBe("sandbox");
    expect(r.headers.get("content-disposition")).toContain("inline");
    expect(r.headers.get("x-frame-options")).toBeNull();
    expect(r.headers.get("server")).toBeNull();
  });

  it("keeps the API's Cache-Control when it sets one", async () => {
    const api = fakeApi();
    api.on("GET", "/x", () => new Response("{}", { headers: { "cache-control": "private, max-age=60" } }));
    const r = await relay(portalRequest("/api/backend/x", { cookies: SIGNED_IN }));
    expect(r.headers.get("cache-control")).toBe("private, max-age=60");
  });

  it.each([
    "/api/backend/auth/refresh",
    "/api/backend/auth/otp/verify",
    "/api/backend/auth/login",
    "/api/backend/AUTH/refresh",
    "/api/backend/me/password",
    "/api/backend/me/password/",
    "/api/backend/docs",
    "/api/backend/docs/oauth2-redirect",
    "/api/backend/redoc",
    "/api/backend/openapi.json",
    "/api/backend/admin/../auth/refresh",
    "/api/backend/admin/%2e%2e/auth/refresh",
    "/api/backend/admin/./users",
    "/api/backend/admin%2Fusers",
    "/api/backend/admin%5cusers",
    "/api/backend//me",
    "/api/backend/admin\\users",
    "/api/backend/",
  ])("refuses %s", (path) => {
    expect(targetPath(ORIGIN + path)).toBeNull();
  });

  it("keeps a normal path and its query", () => {
    expect(targetPath(ORIGIN + "/api/backend/admin/users?q=ab&limit=50")).toBe("/admin/users?q=ab&limit=50");
    expect(targetPath(ORIGIN + "/api/backend/admin/tickets/TKT-EDU-2026-0001")).toBe(
      "/admin/tickets/TKT-EDU-2026-0001",
    );
    expect(targetPath(ORIGIN + "/api/backend/me/profile")).toBe("/me/profile");
  });

  it.each(["/api/backend/auth/refresh", "/api/backend/openapi.json", "/api/backend/admin%2Fusers"])(
    "answers 404 for %s and calls nothing",
    async (path) => {
      const api = fakeApi();
      const r = await relay(portalRequest(path, { cookies: SIGNED_IN }));
      expect(r.status).toBe(404);
      expect(api.calls).toHaveLength(0);
    },
  );

  it("retries once after a 401 with the refreshed token", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () =>
      jsonResponse(200, { access_token: "A2", refresh_token: "R2", expires_in: 1800 }),
    );
    api.on("GET", "/me", (call) =>
      call.headers.get("authorization") === "Bearer A2"
        ? jsonResponse(200, { ok: 1 })
        : jsonResponse(401, { detail: "token is not valid" }),
    );
    const ok = await relay(portalRequest("/api/backend/me", { cookies: SIGNED_IN }));
    expect(ok.status).toBe(200);
    expect(setCookies(ok).aslms_at).toContain("aslms_at=A2");
    expect(api.calls.map((c) => c.path)).toEqual(["/me", "/auth/refresh", "/me"]);
  });

  it("answers 401 signed_out when the retry is refused too", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () =>
      jsonResponse(200, { access_token: "A3", refresh_token: "R3", expires_in: 1800 }),
    );
    api.on("GET", "/me", () => jsonResponse(401, { detail: "token is not valid" }));
    const out = await relay(portalRequest("/api/backend/me", { cookies: SIGNED_IN }));
    expect(out.status).toBe(401);
    expect((await out.json()).detail.code).toBe("signed_out");
    expect(api.calls.map((c) => c.path)).toEqual(["/me", "/auth/refresh", "/me"]);
    expect(setCookies(out).aslms_rt).toContain("Max-Age=0");
  });

  it("streams a multipart body, also on the retry", async () => {
    const api = fakeApi();
    api.on("POST", "/auth/refresh", () =>
      jsonResponse(200, { access_token: "A2", refresh_token: "R2", expires_in: 1800 }),
    );
    api.on("POST", "/admin/tickets/T-1/documents", (call) =>
      call.headers.get("authorization") === "Bearer A2"
        ? jsonResponse(201, { type: call.headers.get("content-type"), body: call.body })
        : jsonResponse(401, { detail: "token is not valid" }),
    );
    const form = new FormData();
    form.append("file", new Blob(["%PDF-1.4 hello"], { type: "application/pdf" }), "order.pdf");
    const encoded = new Response(form);
    const type = encoded.headers.get("content-type")!;
    const r = await relay(
      portalRequest("/api/backend/admin/tickets/T-1/documents", {
        method: "POST",
        cookies: SIGNED_IN,
        headers: { "content-type": type },
        body: encoded.body,
      }),
    );
    expect(r.status).toBe(201);
    const data = await r.json();
    expect(data.type).toBe(type);
    expect(data.body).toContain("%PDF-1.4 hello");
    expect(data.body).toContain('filename="order.pdf"');
  });

  it("answers 502 api_unavailable when the API does not answer in time", async () => {
    process.env.RELAY_TIMEOUT_SECONDS = "0.05";
    const api = fakeApi();
    api.fetchMock.mockImplementationOnce(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    const r = await relay(portalRequest("/api/backend/slow", { cookies: SIGNED_IN }));
    expect(r.status).toBe(502);
    expect((await r.json()).detail.code).toBe("api_unavailable");
  });

  it("answers 401 signed_out without calling the API when there is no session", async () => {
    const api = fakeApi();
    const r = await relay(portalRequest("/api/backend/me"));
    expect(r.status).toBe(401);
    expect(api.calls).toHaveLength(0);
  });

  it("refuses a write without the portal header", async () => {
    const api = fakeApi();
    const r = await relay(
      portalRequest("/api/backend/admin/users", { method: "POST", cookies: SIGNED_IN, portal: false, body: "{}" }),
    );
    expect(r.status).toBe(403);
    expect(api.calls).toHaveLength(0);
  });
});

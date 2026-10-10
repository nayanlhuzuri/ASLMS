import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, apiPage, ApiError, parseError, resetClientHooks, session, setClientHooks } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

const navigate = vi.fn();
const clearCache = vi.fn();

beforeEach(() => {
  navigate.mockReset();
  clearCache.mockReset();
  setClientHooks({ navigate, clearCache, currentPath: () => "/admin/users?q=ab" });
});

afterEach(() => {
  resetClientHooks();
});

describe("parseError", () => {
  it("reads {code, message, ...extra}", () => {
    const e = parseError(401, { detail: { code: "otp_invalid", message: "wrong code", attempts_left: 3 } });
    expect(e).toMatchObject({ status: 401, code: "otp_invalid", message: "wrong code", extra: { attempts_left: 3 } });
  });

  it("reads a plain string detail", () => {
    const e = parseError(403, { detail: "users.create is not enabled for you" });
    expect(e).toMatchObject({ status: 403, code: "forbidden", message: "users.create is not enabled for you" });
  });

  it("reads the 422 list", () => {
    const e = parseError(422, {
      detail: [
        { loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" },
        { loc: ["body", "password"], msg: "too short", type: "string_too_short" },
      ],
    });
    expect(e.code).toBe("validation");
    expect(e.message).toBe("email: value is not a valid email address; password: too short");
    expect(e.extra.fields).toHaveLength(2);
  });

  it("keeps the extra fields of an object without a code (office in use)", () => {
    const e = parseError(409, { detail: { message: "in use", counts: { users: 2 } } });
    expect(e).toMatchObject({ code: "conflict", message: "in use", extra: { counts: { users: 2 } } });
  });
});

describe("api", () => {
  it("calls the relay with the portal header and returns the body", async () => {
    const fetchMock = vi.fn(async () => respond(200, { ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api("/me", { query: { a: "x", b: undefined, c: "" } })).toEqual({ ok: 1 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/backend/me?a=x");
    expect((init.headers as Record<string, string>)["X-ASLMS-Request"]).toBe("1");
  });

  it("returns X-Total-Count with a page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(200, [1, 2], { "x-total-count": "120" })));
    expect(await apiPage("/admin/users")).toEqual({ items: [1, 2], total: 120 });
  });

  it.each([
    ["password_change_required", "/welcome/password"],
    ["profile_confirmation_required", "/welcome/profile"],
  ])("%s sends the browser to %s", async (code, page) => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(403, { detail: { code, message: "first" } })));
    await expect(api("/dashboard")).rejects.toBeInstanceOf(ApiError);
    expect(navigate).toHaveBeenCalledWith(page);
  });

  it("signed_out clears the query cache and goes to /login?next=", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(401, { detail: { code: "signed_out", message: "x" } })));
    await expect(api("/me")).rejects.toMatchObject({ code: "signed_out" });
    expect(clearCache).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledWith("/login?next=%2Fadmin%2Fusers%3Fq%3Dab");
  });

  it("a wrong sign-in code is an error, not a sign-out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => respond(401, { detail: { code: "otp_invalid", message: "x", attempts_left: 2 } })),
    );
    await expect(session("verify", { code: "000000" })).rejects.toMatchObject({ code: "otp_invalid" });
    expect(navigate).not.toHaveBeenCalled();
    expect(clearCache).not.toHaveBeenCalled();
  });

  it("a network failure is an ApiError with the code network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(api("/me")).rejects.toMatchObject({ code: "network", status: 0 });
  });
});

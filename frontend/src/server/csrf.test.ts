// @vitest-environment node
import { describe, expect, it } from "vitest";

import { csrfRefusal } from "./csrf";

const PORTAL = "http://localhost:3000";

describe("cross-site check", () => {
  it("refuses a non-GET request without the portal header", async () => {
    const r = csrfRefusal(new Request(PORTAL + "/api/backend/admin/users", { method: "POST" }));
    expect(r?.status).toBe(403);
    expect((await r!.json()).detail.code).toBe("csrf");
  });

  it("refuses a foreign Origin even with the header", () => {
    const r = csrfRefusal(
      new Request(PORTAL + "/x", { method: "POST", headers: { "x-aslms-request": "1", origin: "https://evil.example" } }),
    );
    expect(r?.status).toBe(403);
  });

  it("passes the same origin with the header, and a request without Origin", () => {
    expect(
      csrfRefusal(new Request(PORTAL + "/x", { method: "PUT", headers: { "x-aslms-request": "1", origin: PORTAL } })),
    ).toBeNull();
    expect(csrfRefusal(new Request(PORTAL + "/x", { method: "DELETE", headers: { "x-aslms-request": "1" } }))).toBeNull();
  });

  it("passes GET", () => {
    expect(csrfRefusal(new Request(PORTAL + "/x", { headers: { origin: "https://evil.example" } }))).toBeNull();
  });
});

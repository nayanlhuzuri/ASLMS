import { describe, expect, it } from "vitest";

import { apiCasePath, casePath, refPath } from "./refs";

describe("references in URLs", () => {
  it("writes every / of a ref_no as -", () => {
    expect(refPath("ASLMS/GOA/CASE/2026/000123")).toBe("ASLMS-GOA-CASE-2026-000123");
  });

  it("leaves a CNR unchanged", () => {
    expect(refPath("ASHC010012342026")).toBe("ASHC010012342026");
  });

  it("builds the case page and its tabs", () => {
    expect(casePath("ASLMS/GOA/CASE/2026/000123")).toBe("/cases/ASLMS-GOA-CASE-2026-000123");
    expect(casePath("ASHC010012342026", "orders")).toBe("/cases/ASHC010012342026/orders");
  });

  it("API paths always use the dash form (the relay refuses an encoded slash)", () => {
    expect(apiCasePath("ASLMS/GOA/CASE/2026/000123", "claim")).toBe("/cases/ASLMS-GOA-CASE-2026-000123/claim");
    expect(apiCasePath("ASLMS-GOA-CASE-2026-000123")).toBe("/cases/ASLMS-GOA-CASE-2026-000123");
    expect(apiCasePath("ASLMS/GOA/CASE/2026/000123")).not.toMatch(/%2F/i);
  });
});

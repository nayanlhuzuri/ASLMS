import { describe, expect, it } from "vitest";

import { apiCasePath, casePath, currentCaseHref, refPath } from "./refs";

describe("references in URLs", () => {
  it("writes every / of a ref_no as -", () => {
    expect(refPath("ASLMS/GHC/CASE/2026/000123")).toBe("ASLMS-GHC-CASE-2026-000123");
  });

  it("leaves a CNR unchanged", () => {
    expect(refPath("ASHC010012342026")).toBe("ASHC010012342026");
  });

  it("builds the case page and its tabs", () => {
    expect(casePath("ASLMS/GHC/CASE/2026/000123")).toBe("/cases/ASLMS-GHC-CASE-2026-000123");
    expect(casePath("ASHC010012342026", "orders")).toBe("/cases/ASHC010012342026/orders");
  });

  it("API paths always use the dash form (the relay refuses an encoded slash)", () => {
    expect(apiCasePath("ASLMS/GHC/CASE/2026/000123", "claim")).toBe("/cases/ASLMS-GHC-CASE-2026-000123/claim");
    expect(apiCasePath("ASLMS-GHC-CASE-2026-000123")).toBe("/cases/ASLMS-GHC-CASE-2026-000123");
    expect(apiCasePath("ASLMS/GHC/CASE/2026/000123")).not.toMatch(/%2F/i);
  });
});

// design case-ref-court-prefix, decision 20: this alias test keeps an old GOA case number on purpose
describe("an outdated case address", () => {
  const NEW = "ASLMS/GHC/CASE/2026/000001";

  it("gives way to the current number, keeping the tab and the query", () => {
    expect(currentCaseHref("/cases/ASLMS-GOA-CASE-2026-000001/orders", "page=2", "ASLMS-GOA-CASE-2026-000001", NEW)).toBe(
      "/cases/ASLMS-GHC-CASE-2026-000001/orders?page=2",
    );
    expect(currentCaseHref("/cases/ASLMS-GOA-CASE-2026-000001", "", "ASLMS/GOA/CASE/2026/000001", NEW)).toBe(
      "/cases/ASLMS-GHC-CASE-2026-000001",
    );
  });

  it("is left alone when it is current, an id or a CNR", () => {
    expect(currentCaseHref("/cases/ASLMS-GHC-CASE-2026-000001/orders", "", "ASLMS-GHC-CASE-2026-000001", NEW)).toBeNull();
    expect(currentCaseHref("/cases/ASLMS-GHC-CASE-2026-000001", "", "ASLMS/GHC/CASE/2026/000001", NEW)).toBeNull();
    expect(currentCaseHref("/cases/GAHC010000012025/orders", "", "GAHC010000012025", NEW)).toBeNull();
    expect(currentCaseHref("/cases/0192a3b4-0000-7000-8000-000000000001", "", "0192a3b4-0000-7000-8000-000000000001", NEW)).toBeNull();
  });
});

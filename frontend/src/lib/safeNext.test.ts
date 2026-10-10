import { describe, expect, it } from "vitest";

import { safeNext } from "./safeNext";

describe("safeNext", () => {
  it.each(["//evil.example", "https://evil.example/x", "/\\evil.example", "", "javascript:alert(1)", "admin", null])(
    "sends %s to the dashboard",
    (value) => {
      expect(safeNext(value)).toBe("/");
    },
  );

  it("keeps a relative path and its query", () => {
    expect(safeNext("/admin/users")).toBe("/admin/users");
    expect(safeNext("/admin/tickets/TKT-EDU-2026-0001?x=1")).toBe("/admin/tickets/TKT-EDU-2026-0001?x=1");
  });
});

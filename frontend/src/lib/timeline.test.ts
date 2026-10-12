import { describe, expect, it } from "vitest";

import { timelineDetail } from "./timeline";

describe("timeline lines", () => {
  it("formats the common types from their payload keys", () => {
    expect(timelineDetail("next_date_changed", { next_hearing_date: ["2026-10-01", "2026-10-15"] })).toBe(
      "1 Oct 2026 → 15 Oct 2026",
    );
    expect(timelineDetail("order_stored", { order_no: "3", order_date: "2026-09-25" })).toBe("Order 3 · 25 Sep 2026");
    expect(timelineDetail("status_changed", { status: ["pending", "disposed"] })).toBe("pending → disposed");
    expect(timelineDetail("claimed", { office_code: "EDU", role: "primary" })).toBe("EDU · primary");
    expect(timelineDetail("transfer_requested", { from_office_code: "EDU", to_office_code: "HEALTH", ref_no: "T/1" })).toBe(
      "EDU → HEALTH · T/1",
    );
    expect(timelineDetail("suggested_elsewhere", { from_office_code: null, to_office_code: "FIN" })).toBe("— → FIN");
    expect(timelineDetail("case_taken_over", { from_user_name: "A", to_user_name: "B", office_code: "EDU" })).toBe(
      "A → B · EDU",
    );
    expect(timelineDetail("case_merged", { merged_ref_no: "ASLMS/GOA/CASE/2026/000009" })).toBe(
      "Provisional ASLMS/GOA/CASE/2026/000009 merged into this case",
    );
  });

  it("an unknown type gives no detail", () => {
    expect(timelineDetail("config_changed", { key: "x" })).toBeNull();
  });

  it("never prints raw JSON", () => {
    expect(timelineDetail("claimed", { office_code: { nested: true } })).toBeNull();
    expect(timelineDetail("status_changed", { status: "odd" })).toBeNull();
    expect(timelineDetail("claimed", "text")).toBeNull();
  });
});

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
    expect(timelineDetail("case_merged", { merged_ref_no: "ASLMS/GHC/CASE/2026/000009" })).toBe(
      "Provisional ASLMS/GHC/CASE/2026/000009 merged into this case",
    );
  });

  it("formats the workflow types (portal-workflow, decision 19) with the given labels", () => {
    const labels = {
      reasons: { sent: "Sent", recalled: "Recalled" },
      actions: { parawise_comments: "Parawise comments" },
      kinds: { opinion: "Opinion" },
      alertKinds: { file_received: "File received" },
    };
    expect(
      timelineDetail(
        "custody_moved",
        {
          reason: "sent",
          office_code: "HEALTH",
          user_name: "Health Off",
          holder_designation: "Under Secretary",
          pending_action: "parawise_comments",
          due_date: "2026-10-20",
          remark: "must never show",
        },
        labels,
      ),
    ).toBe("Sent · HEALTH · Health Off, Under Secretary · Parawise comments · due 20 Oct 2026");
    expect(timelineDetail("custody_moved", { reason: "recalled", office_code: "EDU", pending_action: "examine" }, labels)).toBe(
      "Recalled · EDU · examine",
    );
    expect(timelineDetail("stage_set", { stage: "reply_due", label: "Reply due", office_code: "EDU" })).toBe("Reply due · EDU");
    expect(timelineDetail("note_added", { kind: "opinion", ref_no: "ASLMS/EDU/NOTE/2026/000003", finalised: true }, labels)).toBe(
      "Opinion · ASLMS/EDU/NOTE/2026/000003 · from a draft",
    );
    expect(timelineDetail("note_added", { kind: "opinion", ref_no: "N/1", finalised: false }, labels)).toBe("Opinion · N/1");
    expect(timelineDetail("document_uploaded", { doc_type: "counter_affidavit", office_code: "EDU" })).toBe(
      "counter affidavit · EDU",
    );
    expect(timelineDetail("alert_raised", { kind: "file_received", title: "x" }, labels)).toBe("File received");
  });

  it("never shows a remark, and never raw JSON from workflow payloads", () => {
    const line = timelineDetail("custody_moved", { reason: "sent", remark: "secret remark", office_code: { x: 1 } });
    expect(line).toBe("sent");
    expect(line).not.toContain("secret");
    expect(timelineDetail("note_added", { kind: ["x"], ref_no: { y: 1 } })).toBeNull();
  });

  it("an unknown type gives no detail", () => {
    expect(timelineDetail("config_changed", { key: "x" })).toBeNull();
  });

  it("never prints raw JSON", () => {
    expect(timelineDetail("claimed", { office_code: { nested: true } })).toBeNull();
    expect(timelineDetail("status_changed", { status: "odd" })).toBeNull();
    expect(timelineDetail("claimed", "text")).toBeNull();
  });

  it("the next-date lines read payload keys only and never print a note (portal-next-dates, decision 15)", () => {
    const extracted = {
      order_no: "4",
      order_date: "2026-10-12",
      next_date: "2026-10-26",
      review: true,
      status: "period",
      rule: "list_after_period",
    };
    expect(timelineDetail("next_date_extracted", extracted)).toBe("Order 4 of 12 Oct 2026 · 26 Oct 2026 · to be confirmed");
    expect(timelineDetail("next_date_extracted", { ...extracted, next_date: "2026-11-15", review: false })).toBe(
      "Order 4 of 12 Oct 2026 · 15 Nov 2026",
    );
    expect(timelineDetail("next_date_extracted", { order_no: "5", order_date: "2026-10-13", next_date: null, review: true })).toBe(
      "Order 5 of 13 Oct 2026 · no date read",
    );
    expect(timelineDetail("next_date_reviewed", { action: "confirm", next_date: "2026-10-26", office_code: "EDU" })).toBe(
      "Confirmed · 26 Oct 2026 · EDU",
    );
    expect(timelineDetail("next_date_reviewed", { action: "reject", next_date: "2026-10-26", office_code: "EDU" })).toBe(
      "Not accepted · 26 Oct 2026 · EDU",
    );
    const entered = { next_date: "2026-11-02", office_code: "EDU", ref_no: "ASLMS-EDU-NXT-2026-000001", note: "a private remark" };
    expect(timelineDetail("next_date_entered", entered)).toBe("2 Nov 2026 · EDU · ASLMS-EDU-NXT-2026-000001");
    for (const type of ["next_date_extracted", "next_date_reviewed", "next_date_entered"]) {
      expect(timelineDetail(type, { ...entered, review: true }) ?? "").not.toContain("private");
    }
  });
});

describe("recommendation_closed (ownership-refinements, decision 10)", () => {
  it("names the closed department and the claimer", () => {
    expect(timelineDetail("recommendation_closed", { office_code: "HEALTH", claimed_by_office_code: "EDU" })).toBe(
      "HEALTH — claimed by EDU",
    );
    expect(timelineDetail("recommendation_closed", { office_code: "HEALTH" })).toBe("HEALTH");
    expect(timelineDetail("recommendation_closed", {})).toBeNull();
  });
});

describe("next_date_differs (design next-date-direct, decision 5)", () => {
  it("names the order's date and the court's", () => {
    expect(
      timelineDetail("next_date_differs", { court_date: "2026-11-25", order_next_date: "2026-11-20", order_date: "2026-10-12" }),
    ).toBe("The order of 12 Oct 2026 gives 20 Nov 2026; the court's record gives 25 Nov 2026");
    expect(timelineDetail("next_date_differs", { court_date: "2026-11-25" })).toBeNull();
  });
});

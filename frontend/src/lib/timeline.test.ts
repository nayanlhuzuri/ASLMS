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
});

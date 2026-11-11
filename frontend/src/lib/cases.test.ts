import { describe, expect, it } from "vitest";

import type { CustodyCard, SentItem } from "./api/types";
import { cardHolder, cardSender, isNewSince, legHolder, sentDue, withText } from "./cases";

// 25 Oct 2026, 12:00 IST
const NOW = new Date("2026-10-25T06:30:00Z");

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: false,
    closed: false,
    due_date: "2026-11-30",
    holder_office: { code: "EDU-DSE", name: "Secondary Education" },
    holder_user: { id: "u-7", full_name: "Officer One", designation: "Section Officer" },
    leg_seq_no: 2,
    overdue: false,
    overdue_days: 0,
    pending_action: "examine",
    pending_action_label: "Examine",
    reason: "sent",
    remark: null,
    sent_by: { name: "Edu Admin", designation: "Joint Secretary", office_code: "EDU" },
    since: "2026-10-01T10:00:00Z",
    ...extra,
  };
}


function sentRow(current: boolean | null, due: string | null): SentItem {
  return {
    case: {} as SentItem["case"],
    visible: current !== null,
    current,
    leg: {
      seq_no: 2,
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { id: "u-h1", full_name: "Health Off" },
      holder_designation: "Under Secretary",
      reason: "sent",
      reason_label: "Sent",
      pending_action: "examine",
      pending_action_label: "Examine",
      due_date: due,
      remark: null,
      started_at: "2026-10-13T10:00:00Z",
      actor_name: "Anita Sharma",
      actor_designation: "Under Secretary",
      actor_office_code: "EDU",
    },
  };
}

describe("isNewSince and sentDue (portal-screen-fixes-work, decisions 3 and 5)", () => {
  it("New within 48 hours of receipt, not before or after", () => {
    expect(isNewSince("2026-10-23T06:30:00Z", NOW)).toBe(true);
    expect(isNewSince("2026-10-23T06:29:00Z", NOW)).toBe(false);
    expect(isNewSince("2026-10-26T06:30:00Z", NOW)).toBe(false);
    expect(isNewSince(null, NOW)).toBe(false);
  });

  it("Sent by Me: overdue by whole IST days, due soon within the window, a moved-on leg only its date", () => {
    expect(sentDue(sentRow(true, "2026-10-22"), NOW)).toEqual({ date: "2026-10-22", overdue: true, overdueDays: 3, dueSoon: false });
    expect(sentDue(sentRow(true, "2026-10-27"), NOW)).toEqual({ date: "2026-10-27", overdue: false, overdueDays: 0, dueSoon: true });
    expect(sentDue(sentRow(true, "2026-10-28"), NOW)).toEqual({ date: "2026-10-28", overdue: false, overdueDays: 0, dueSoon: false });
    expect(sentDue(sentRow(true, null), NOW)).toEqual({ date: null, overdue: false, overdueDays: 0, dueSoon: false });
    expect(sentDue(sentRow(false, "2026-10-24"), NOW)).toEqual({ date: "2026-10-24", overdue: false, overdueDays: 0, dueSoon: false });
    expect(sentDue(sentRow(null, "2026-10-24"), NOW).overdue).toBe(false);
  });
});

describe("withText (decision 13)", () => {
  it("designation and office, with (you) for the caller and the name as the title", () => {
    expect(withText({ designation: "Section Officer", office: "Secondary Education", name: "Officer One", userId: "u-7" })).toEqual({
      text: "Section Officer, Secondary Education",
      title: "Officer One",
    });
    expect(withText({ designation: "Section Officer", office: "Secondary Education", name: "Officer One", userId: "u-7" }, "u-7").text).toBe(
      "Section Officer, Secondary Education (you)",
    );
  });

  it("an office with no officer reads as the office; the name shows only without a designation", () => {
    expect(withText(cardHolder(card({ holder_user: null }))).text).toBe("Secondary Education");
    expect(withText({ designation: null, office: "Health", name: "Health Off" }).text).toBe("Health Off, Health");
    expect(withText({ designation: "  ", office: "Health", name: "Health Off" }).text).toBe("Health Off, Health");
    expect(withText(null).text).toBe("—");
  });

  it("reads the holder and sender of a card and the holder of a leg", () => {
    expect(withText(cardHolder(card())).text).toBe("Section Officer, Secondary Education");
    expect(withText(cardSender(card())).text).toBe("Joint Secretary, EDU");
    expect(cardSender(card({ sent_by: null }))).toBeNull();
    expect(withText(legHolder(sentRow(true, null).leg), "u-h1").text).toBe("Under Secretary, Health (you)");
  });
});

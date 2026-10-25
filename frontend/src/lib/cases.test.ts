import { describe, expect, it } from "vitest";

import type { CustodyCard, HeldItem, SentItem } from "./api/types";
import { cardHolder, cardSender, hearingCountdown, leadBadge, legHolder, withText } from "./cases";

// 25 Oct 2026, 12:00 IST
const NOW = new Date("2026-10-25T06:30:00Z");

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: false,
    can_send: false,
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

const heldRow = (extra: Partial<CustodyCard> = {}): HeldItem => ({ case: {} as HeldItem["case"], card: card(extra) });

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

describe("leadBadge (case-workspace-admin, decision 19), first match wins", () => {
  it("Cases with me: Overdue, Due soon, New within 48 h, else no badge", () => {
    expect(leadBadge(heldRow({ overdue: true, due_soon: false }), "with-me", NOW)).toEqual({ label: "Overdue", tone: "danger" });
    // overdue wins over due soon and new
    expect(leadBadge(heldRow({ overdue: true, due_soon: true, since: "2026-10-25T06:00:00Z" }), "with-me", NOW)!.label).toBe("Overdue");
    expect(leadBadge(heldRow({ due_soon: true, since: "2026-10-25T06:00:00Z" }), "with-me", NOW)).toEqual({ label: "Due soon", tone: "warning" });
    // the 48 h edge: exactly 48 h ago is still new, a minute more is not
    expect(leadBadge(heldRow({ since: "2026-10-23T06:30:00Z" }), "with-me", NOW)).toEqual({ label: "New", tone: "info" });
    expect(leadBadge(heldRow({ since: "2026-10-23T06:29:00Z" }), "with-me", NOW)).toBeNull();
    expect(leadBadge(heldRow(), "with-me", NOW)).toBeNull();
    expect(leadBadge({ case: {} as HeldItem["case"], card: null }, "with-me", NOW)).toBeNull();
  });

  it("Pending action: Overdue, Due soon, else Waiting (never New)", () => {
    expect(leadBadge(heldRow({ overdue: true }), "pending", NOW)!.label).toBe("Overdue");
    expect(leadBadge(heldRow({ due_soon: true }), "pending", NOW)!.label).toBe("Due soon");
    expect(leadBadge(heldRow({ since: "2026-10-25T06:00:00Z" }), "pending", NOW)).toEqual({ label: "Waiting" });
    expect(leadBadge(heldRow(), "pending", NOW)).toEqual({ label: "Waiting" });
  });

  it("Sent by me: only while the leg is current, Overdue, Due soon or Waiting; nothing when not current or not known", () => {
    expect(leadBadge(sentRow(true, "2026-10-24"), "sent", NOW)).toEqual({ label: "Overdue", tone: "danger" });
    expect(leadBadge(sentRow(true, "2026-10-27"), "sent", NOW)).toEqual({ label: "Due soon", tone: "warning" });
    expect(leadBadge(sentRow(true, "2026-10-28"), "sent", NOW)).toEqual({ label: "Waiting" });
    expect(leadBadge(sentRow(true, null), "sent", NOW)).toEqual({ label: "Waiting" });
    expect(leadBadge(sentRow(false, "2026-10-24"), "sent", NOW)).toBeNull();
    expect(leadBadge(sentRow(null, "2026-10-24"), "sent", NOW)).toBeNull();
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

describe("hearingCountdown (decision 11): whole IST days, never hours", () => {
  it("Today, Tomorrow, In n days; nothing for a past date or none", () => {
    expect(hearingCountdown("2026-10-25", NOW)).toBe("Today");
    expect(hearingCountdown("2026-10-26", NOW)).toBe("Tomorrow");
    expect(hearingCountdown("2026-10-30", NOW)).toBe("In 5 days");
    expect(hearingCountdown("2026-10-24", NOW)).toBeNull();
    expect(hearingCountdown(null, NOW)).toBeNull();
  });

  it("counts in IST across midnight, not in the browser's or UTC's day", () => {
    // 25 Oct 23:30 IST is still the 25th: the 26th is tomorrow
    expect(hearingCountdown("2026-10-26", new Date("2026-10-25T18:00:00Z"))).toBe("Tomorrow");
    // 26 Oct 00:30 IST (still the 25th in UTC): the 26th is today
    expect(hearingCountdown("2026-10-26", new Date("2026-10-25T19:00:00Z"))).toBe("Today");
  });
});

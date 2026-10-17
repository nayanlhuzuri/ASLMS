import { describe, expect, it } from "vitest";

import type { NextDate } from "./api/types";
import { isScannedItem, originLine, readingLabel, ruleHint, sourceLabel, statusLabel } from "./nextDates";

function row(extra: Partial<NextDate> = {}): NextDate {
  return {
    id: "nd-1",
    ref_no: null,
    next_date: "2026-11-20",
    source: "order_specific",
    confidence: 0.95,
    needs_review: false,
    review_status: "not_needed",
    order: { id: "o-1", order_no: "4", order_date: "2026-10-12", document_id: "d-1", phrase: "List on 20.11.2026", rule: "list_on_date" },
    note: null,
    reviewed_by: null,
    reviewed_at: null,
    created_by: null,
    created_at: "2026-10-12T10:00:00Z",
    ...extra,
  };
}

describe("next-date words (portal-next-dates, decision 12)", () => {
  it("names every source and status, and an unknown code by its words", () => {
    expect(sourceLabel("causelist")).toBe("Cause list");
    expect(sourceLabel("current_status")).toBe("Court records");
    expect(sourceLabel("order_specific")).toBe("Date in the order");
    expect(sourceLabel("order_period")).toBe("Counted from the order");
    expect(sourceLabel("manual")).toBe("Entered by hand");
    expect(sourceLabel("something_new")).toBe("something new");
    expect(statusLabel("not_needed")).toBe("In use");
    expect(statusLabel("confirmed")).toBe("Confirmed");
    expect(statusLabel("rejected")).toBe("Not accepted");
    expect(statusLabel("superseded")).toBe("Replaced by a later date");
    expect(statusLabel("expired")).toBe("Date passed before it was confirmed");
    expect(statusLabel("odd_state")).toBe("odd state");
  });

  it("a pending date reads differently with and without the action", () => {
    expect(statusLabel("pending", { canAct: true })).toBe("Suggested from the order — please confirm");
    expect(statusLabel("pending", { canAct: false })).toBe("Waiting for confirmation");
    expect(statusLabel("pending")).toBe("Waiting for confirmation");
  });

  it("gives a hint for the known rules and none for an unknown or missing rule", () => {
    expect(ruleHint("returnable_date")).toBe("The order gives this as the returnable date of the notice");
    expect(ruleHint("qualified_date")).toBe("The order says not before this date — please check the exact day");
    for (const r of ["list_after_period", "after_returnable_period", "returnable_period"]) {
      expect(ruleHint(r)).toBe("Counted from the order date — the order gives a period, not a date");
    }
    expect(ruleHint("conflicting_dates")).toBe("The order gives more than one date");
    expect(ruleHint("no_countable_date")).toBe("The order gives no date that could be counted");
    expect(ruleHint("brand_new_rule")).toBeNull();
    expect(ruleHint(null)).toBeNull();
  });

  it("reads an order's six statuses in plain words (decision 11)", () => {
    expect(readingLabel({ next_date_status: "specific", next_date_found: "2026-11-20" })).toEqual({
      date: "20 Nov 2026",
      words: "Date in the order",
    });
    expect(readingLabel({ next_date_status: "period", next_date_found: "2026-10-26" })).toEqual({
      date: "26 Oct 2026",
      words: "counted from the order",
    });
    expect(readingLabel({ next_date_status: "unclear", next_date_found: null })).toEqual({ date: null, words: "No clear date" });
    expect(readingLabel({ next_date_status: "none" })).toEqual({ date: null, words: "No next date given" });
    expect(readingLabel({ next_date_status: "no_text" })).toEqual({ date: null, words: "Could not be read (scanned copy)" });
    expect(readingLabel({ next_date_status: "pending" })).toEqual({ date: null, words: "Not read yet" });
    expect(readingLabel({ next_date_status: null })).toBeNull();
  });

  it("says where a date came from (decision 8)", () => {
    expect(originLine(row())).toBe("Fixed in the order of 12 Oct 2026");
    expect(
      originLine(
        row({
          source: "order_period",
          review_status: "confirmed",
          reviewed_by: { name: "Edu Admin" },
          reviewed_at: "2026-10-14T05:00:00Z",
        }),
      ),
    ).toBe("Counted from the order of 12 Oct 2026 · confirmed by Edu Admin on 14 Oct 2026");
    expect(
      originLine(row({ source: "manual", order: null, created_by: { name: "Officer One" }, created_at: "2026-10-15T05:00:00Z" })),
    ).toBe("Entered by Officer One on 15 Oct 2026");
    expect(originLine(row({ source: "current_status", order: null }))).toBe("From the court records");
  });

  it("an enter item with neither rule nor sentence is a scanned order", () => {
    expect(isScannedItem({ kind: "enter", rule: null, phrase: null })).toBe(true);
    expect(isScannedItem({ kind: "enter", rule: "no_countable_date", phrase: "List after the vacation" })).toBe(false);
    expect(isScannedItem({ kind: "confirm", rule: null, phrase: null })).toBe(false);
  });
});

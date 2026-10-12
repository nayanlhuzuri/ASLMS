import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatNumber, formatTime, hearingBadge } from "./format";

describe("IST dates", () => {
  it("shows the IST day for a UTC instant near midnight", () => {
    expect(formatDate("2026-09-24T19:00:00Z")).toBe("25 Sep 2026");
    expect(formatDate("2026-09-24T18:29:00Z")).toBe("24 Sep 2026");
    expect(formatDateTime("2026-09-24T18:30:00Z")).toBe("25 Sep 2026, 00:00");
  });

  it("shows the IST time alone", () => {
    expect(formatTime("2026-10-11T09:04:30Z")).toBe("14:34");
    expect(formatTime(null)).toBe("—");
  });

  it("keeps a plain date as that calendar day", () => {
    expect(formatDate("2026-01-01")).toBe("1 Jan 2026");
  });

  it("shows a dash for nothing", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("Indian digit grouping", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, "1,000"],
    [128400, "1,28,400"],
    [12345678, "1,23,45,678"],
    [-100000, "-1,00,000"],
  ])("%d is %s", (n, text) => {
    expect(formatNumber(n)).toBe(text);
  });
});

describe("hearing badges from IST dates", () => {
  it("counts the IST day near midnight, not the browser's", () => {
    // 18:45 UTC on 24 Sep is 00:15 IST on 25 Sep: a hearing on 24 Sep is already past
    const now = new Date("2026-09-24T18:45:00Z");
    expect(hearingBadge("2026-09-24", now)).toBeNull();
    expect(hearingBadge("2026-09-25", now)).toBe("critical");
    expect(hearingBadge("2026-09-26", now)).toBe("critical");
    expect(hearingBadge("2026-09-27", now)).toBe("week");
    expect(hearingBadge("2026-10-02", now)).toBe("week");
    expect(hearingBadge("2026-10-03", now)).toBeNull();
  });

  it("just before IST midnight the same date is still today", () => {
    const now = new Date("2026-09-24T18:25:00Z"); // 23:55 IST on 24 Sep
    expect(hearingBadge("2026-09-24", now)).toBe("critical");
    expect(hearingBadge(null, now)).toBeNull();
  });
});

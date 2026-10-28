import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatDateTimeSeconds, formatNumber, formatTime, isCalendarDay } from "./format";

describe("IST dates", () => {
  it("shows the IST day for a UTC instant near midnight", () => {
    expect(formatDate("2026-09-24T19:00:00Z")).toBe("25 Sep 2026");
    expect(formatDate("2026-09-24T18:29:00Z")).toBe("24 Sep 2026");
    expect(formatDateTime("2026-09-24T18:30:00Z")).toBe("25 Sep 2026, 00:00");
  });

  it("shows an instant to the second in IST across midnight UTC (portal-audit-health)", () => {
    expect(formatDateTimeSeconds("2026-10-14T09:04:07Z")).toBe("14 Oct 2026, 14:34:07");
    expect(formatDateTimeSeconds("2026-10-13T18:29:59Z")).toBe("13 Oct 2026, 23:59:59");
    expect(formatDateTimeSeconds("2026-10-13T18:30:00Z")).toBe("14 Oct 2026, 00:00:00");
    expect(formatDateTimeSeconds(null)).toBe("—");
    expect(formatDateTimeSeconds("not a date")).toBe("not a date");
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

describe("isCalendarDay (design next-hearing-highlight)", () => {
  it("accepts real days, a leap day among them, and refuses impossible or malformed ones", () => {
    for (const d of ["2026-10-27", "2026-12-31", "2027-01-01", "2028-02-29"]) expect(isCalendarDay(d)).toBe(true);
    for (const d of ["2026-02-30", "2026-04-31", "2027-02-29", "2026-13-01", "2026-00-10", "28/10/2026", "2026-10-28T10:30:00Z", "", null, undefined]) {
      expect(isCalendarDay(d)).toBe(false);
    }
  });
});

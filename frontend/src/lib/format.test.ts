import { describe, expect, it } from "vitest";

import { dayMonth, formatDate, formatDateTime, formatDateTimeSeconds, formatMonthYear, formatNumber, formatTime, isCalendarDay, NBSP } from "./format";
import { nb } from "@/test/dates";

describe("IST dates", () => {
  it("shows the IST day for a UTC instant near midnight", () => {
    expect(formatDate("2026-09-24T19:00:00Z")).toBe(nb("25 Sep 2026"));
    expect(formatDate("2026-09-24T18:29:00Z")).toBe(nb("24 Sep 2026"));
    expect(formatDateTime("2026-09-24T18:30:00Z")).toBe(nb("25 Sep 2026, 00:00"));
  });

  it("shows an instant to the second in IST across midnight UTC (portal-audit-health)", () => {
    expect(formatDateTimeSeconds("2026-10-14T09:04:07Z")).toBe(nb("14 Oct 2026, 14:34:07"));
    expect(formatDateTimeSeconds("2026-10-13T18:29:59Z")).toBe(nb("13 Oct 2026, 23:59:59"));
    expect(formatDateTimeSeconds("2026-10-13T18:30:00Z")).toBe(nb("14 Oct 2026, 00:00:00"));
    expect(formatDateTimeSeconds(null)).toBe("—");
    expect(formatDateTimeSeconds("not a date")).toBe("not a date");
  });

  it("shows the IST time alone", () => {
    expect(formatTime("2026-10-11T09:04:30Z")).toBe("14:34");
    expect(formatTime(null)).toBe("—");
  });

  it("keeps a plain date as that calendar day", () => {
    expect(formatDate("2026-01-01")).toBe(nb("1 Jan 2026"));
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

describe("a date never breaks inside itself (design portal-ui-kit-fixes, decision 3)", () => {
  const N = NBSP;
  const GB = { code: "xx", htmlLang: "xx", intl: "en-GB", dir: "ltr" as const };

  it("joins day, month and year with no-break spaces", () => {
    expect(formatDate("2026-10-23")).toBe(`23${N}Oct${N}2026`);
    expect(formatMonthYear("2026-10-23")).toBe(`October${N}2026`);
    expect(formatDateTimeSeconds("2026-10-23T05:30:07Z")).toBe(`23${N}Oct${N}2026, 11:00:07`);
  });

  it("keeps an ordinary space after the comma of a date and time, so the time may go to a second line", () => {
    const text = formatDateTime("2026-10-23T05:30:00Z");
    expect(text).toBe(`23${N}Oct${N}2026, 11:00`);
    expect(text.indexOf(" ")).toBe(text.indexOf(",") + 1);
  });

  it("the Intl path gives the same characters", () => {
    expect(formatDate("2026-10-23", GB)).toBe(formatDate("2026-10-23"));
    expect(formatDateTime("2026-10-23T05:30:00Z", GB)).toBe(formatDateTime("2026-10-23T05:30:00Z"));
    expect(formatMonthYear("2026-10-23", GB)).toBe(formatMonthYear("2026-10-23"));
  });

  it("leaves the time, the chip's day and month, and the weekday alone", () => {
    expect(formatTime("2026-10-23T05:30:00Z")).toBe("11:00");
    expect(dayMonth("2026-10-23")).toEqual({ day: "23", month: "Oct" });
  });
});

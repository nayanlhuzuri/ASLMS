import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatNumber, formatTime } from "./format";

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

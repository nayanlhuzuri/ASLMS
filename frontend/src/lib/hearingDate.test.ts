/**
 * The band of a next hearing date (design next-hearing-highlight, decisions 2, 3, 5 and 6): whole IST days, the
 * browser's zone playing no part. Replaces the tests of the earlier 48-hour badge (format.ts) and countdown (cases.ts).
 */
import { describe, expect, it, vi } from "vitest";

import { HEARING_SOON_DAYS, hearingBand, hearingTone, hearingWords, type HearingBand } from "./hearingDate";

// 12:00 IST on Tuesday 27 Oct 2026
const NOW = new Date("2026-10-27T06:30:00Z");

describe("hearingBand (decision 2)", () => {
  it.each([
    ["2026-10-27", "today", 0],
    ["2026-10-28", "tomorrow", 1],
    ["2026-10-29", "week", 2],
    ["2026-11-03", "week", 7],
    ["2026-11-04", "later", 8],
    ["2026-11-16", "later", 20],
    ["2026-10-26", "passed", -1],
    ["2026-10-22", "passed", -5],
  ] as const)("%s is %s (%d days)", (date, band, days) => {
    expect(hearingBand(date, { now: NOW })).toEqual({ band, days });
  });

  it("no date or a malformed one is none", () => {
    expect(hearingBand(null, { now: NOW })).toEqual({ band: "none", days: null });
    expect(hearingBand(undefined, { now: NOW })).toEqual({ band: "none", days: null });
    expect(hearingBand("", { now: NOW })).toEqual({ band: "none", days: null });
    expect(hearingBand("28/10/2026", { now: NOW })).toEqual({ band: "none", days: null });
    expect(hearingBand("2026-10-28T10:30:00Z", { now: NOW })).toEqual({ band: "none", days: null });
    expect(hearingBand("2026-13-45", { now: NOW })).toEqual({ band: "none", days: null });
  });

  it("a disposed case is disposed whatever date is held", () => {
    for (const date of ["2026-10-27", "2026-10-28", "2026-10-20", "2026-12-01", null]) {
      expect(hearingBand(date, { status: "disposed", now: NOW }).band).toBe("disposed");
    }
    expect(hearingBand("2026-10-28", { status: "pending", now: NOW }).band).toBe("tomorrow");
  });

  it("the soft band ends 7 days ahead", () => {
    expect(HEARING_SOON_DAYS).toBe(7);
  });

  it("counts the IST day across midnight, not the UTC day", () => {
    // 18:29Z on 26 Oct is 23:59 IST on 26 Oct: the 27th is tomorrow
    expect(hearingBand("2026-10-27", { now: new Date("2026-10-26T18:29:00Z") }).band).toBe("tomorrow");
    // 18:31Z on 26 Oct is 00:01 IST on 27 Oct: the 27th is today and the 26th has passed
    const after = new Date("2026-10-26T18:31:00Z");
    expect(hearingBand("2026-10-27", { now: after }).band).toBe("today");
    expect(hearingBand("2026-10-26", { now: after }).band).toBe("passed");
  });

  it.each(["UTC", "America/New_York", "Asia/Kolkata"])("gives the same bands with the browser in %s", (zone) => {
    vi.stubEnv("TZ", zone);
    expect(hearingBand("2026-10-27", { now: new Date("2026-10-26T18:29:00Z") }).band).toBe("tomorrow");
    expect(hearingBand("2026-10-27", { now: new Date("2026-10-26T18:31:00Z") }).band).toBe("today");
    expect(hearingBand("2026-10-26", { now: new Date("2026-10-26T18:31:00Z") }).band).toBe("passed");
    expect(hearingBand("2026-11-03", { now: NOW }).band).toBe("week");
  });

  it("crosses month and year boundaries", () => {
    expect(hearingBand("2027-01-01", { now: new Date("2026-12-31T06:30:00Z") })).toEqual({ band: "tomorrow", days: 1 });
    expect(hearingBand("2026-11-01", { now: new Date("2026-10-31T06:30:00Z") })).toEqual({ band: "tomorrow", days: 1 });
    expect(hearingBand("2027-01-07", { now: new Date("2026-12-31T06:30:00Z") })).toEqual({ band: "week", days: 7 });
    expect(hearingBand("2026-12-31", { now: new Date("2027-01-01T06:30:00Z") })).toEqual({ band: "passed", days: -1 });
  });

  it("defaults to the current instant", () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    try {
      expect(hearingBand("2026-10-27").band).toBe("today");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("hearingWords (decisions 5, 6 and 8)", () => {
  it("names the strong and soft bands in Title Case", () => {
    expect(hearingWords("today", 0)).toBe("Today");
    expect(hearingWords("tomorrow", 1)).toBe("Tomorrow");
    expect(hearingWords("week", 3)).toBe("In 3 Days");
  });

  it("gives the later band no word in the small size and the countdown in the medium size", () => {
    expect(hearingWords("later", 20, { size: "sm" })).toBeNull();
    expect(hearingWords("later", 20)).toBeNull();
    expect(hearingWords("later", 20, { size: "md" })).toBe("In 20 Days");
  });

  it("puts Suggested first for a date read from an order", () => {
    expect(hearingWords("week", 3, { kind: "suggested" })).toBe("Suggested · In 3 Days");
    expect(hearingWords("tomorrow", 1, { kind: "suggested", size: "md" })).toBe("Suggested · Tomorrow");
    expect(hearingWords("later", 20, { kind: "suggested" })).toBe("Suggested");
    expect(hearingWords("later", 20, { kind: "suggested", size: "md" })).toBe("Suggested · In 20 Days");
  });

  it("names a passed date, no date and a disposed case", () => {
    expect(hearingWords("passed", -5)).toBe("Date Passed");
    expect(hearingWords("none", null)).toBe("No Date Yet");
    expect(hearingWords("disposed", 3)).toBe("Disposed");
    expect(hearingWords("disposed", null, { kind: "suggested" })).toBe("Disposed");
    expect(hearingWords("none", null, { kind: "suggested", size: "md" })).toBe("No Date Yet");
  });
});

describe("hearingTone (decision 4)", () => {
  it.each([
    ["today", "strong"],
    ["tomorrow", "strong"],
    ["week", "soft"],
    ["later", "plain"],
    ["passed", "warning"],
    ["none", "muted"],
    ["disposed", "muted"],
  ] as [HearingBand, string][])("%s is %s", (band, tone) => {
    expect(hearingTone(band)).toBe(tone);
  });
});

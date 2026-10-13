import { describe, expect, it } from "vitest";

import {
  acceptOf,
  checkFile,
  dueDateBounds,
  megabytes,
  monthGrid,
  monthRange,
  parseMonth,
  shiftMonth,
  todayIst,
} from "./workflow";

const LIMITS = { max_bytes: 20 * 1024 * 1024, extensions: ["pdf", "docx", "doc", "jpg", "jpeg", "png"] };

describe("due-date bounds", () => {
  it("follow the IST day near midnight", () => {
    // 18:29 UTC is 23:59 IST on the same day; 18:31 UTC is 00:01 IST on the next
    expect(todayIst(new Date("2026-10-13T18:29:00Z"))).toBe("2026-10-13");
    expect(todayIst(new Date("2026-10-13T18:31:00Z"))).toBe("2026-10-14");
    expect(dueDateBounds(new Date("2026-10-13T18:31:00Z"))).toEqual({ min: "2026-10-14", max: "2027-10-14" });
    expect(dueDateBounds(new Date("2027-12-31T20:00:00Z"))).toEqual({ min: "2028-01-01", max: "2028-12-31" });
  });
});

describe("file pre-checks", () => {
  it("refuse a wrong extension and an oversized file from the given limits", () => {
    expect(checkFile({ name: "notes.txt", size: 10 }, LIMITS)).toEqual({ code: "type_not_allowed", extensions: LIMITS.extensions });
    expect(checkFile({ name: "noextension", size: 10 }, LIMITS)?.code).toBe("type_not_allowed");
    expect(checkFile({ name: "big.pdf", size: LIMITS.max_bytes + 1 }, LIMITS)).toEqual({ code: "too_large", maxBytes: LIMITS.max_bytes });
    expect(checkFile({ name: "small.pdf", size: 10 }, { ...LIMITS, max_bytes: 5 })?.code).toBe("too_large");
    expect(checkFile({ name: "empty.pdf", size: 0 }, LIMITS)).toEqual({ code: "empty" });
  });

  it("accept a permitted file whatever the case of its extension", () => {
    expect(checkFile({ name: "Reply.PDF", size: 100 }, LIMITS)).toBeNull();
    expect(checkFile({ name: "scan.jpeg", size: LIMITS.max_bytes }, LIMITS)).toBeNull();
  });

  it("build the input's accept list and the size text", () => {
    expect(acceptOf(LIMITS)).toBe(".pdf,.docx,.doc,.jpg,.jpeg,.png");
    expect(acceptOf(undefined)).toBeUndefined();
    expect(megabytes(20 * 1024 * 1024)).toBe("20 MB");
    expect(megabytes(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(megabytes(300 * 1024)).toBe("300 KB");
    expect(megabytes(50)).toBe("50 bytes");
  });
});

describe("the hearing calendar's month helpers (portal-files-alerts, decision 10)", () => {
  it("a month starting on a Monday has no leading padding", () => {
    const weeks = monthGrid("2026-06");
    expect(weeks).toHaveLength(5);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
    expect(weeks[0]![0]).toBe("2026-06-01");
    expect(weeks[4]).toEqual(["2026-06-29", "2026-06-30", null, null, null, null, null]);
  });

  it("a month starting on a Sunday puts the 1st in the last column", () => {
    const weeks = monthGrid("2026-02");
    expect(weeks[0]).toEqual([null, null, null, null, null, null, "2026-02-01"]);
    expect(weeks[1]![0]).toBe("2026-02-02");
    expect(weeks.flat().filter(Boolean)).toHaveLength(28);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it("February of a leap year has 29 days", () => {
    const weeks = monthGrid("2028-02");
    const days = weeks.flat().filter(Boolean);
    expect(days).toHaveLength(29);
    expect(days.at(-1)).toBe("2028-02-29");
    expect(weeks[0]![0]).toBeNull();
    expect(weeks[0]![1]).toBe("2028-02-01");
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it("monthRange gives the first and last day", () => {
    expect(monthRange("2026-10")).toEqual({ from: "2026-10-01", to: "2026-10-31" });
    expect(monthRange("2026-02")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(monthRange("2028-02")).toEqual({ from: "2028-02-01", to: "2028-02-29" });
  });

  it("shiftMonth crosses a year both ways", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2027-01", -1)).toBe("2026-12");
    expect(shiftMonth("2026-10", 0)).toBe("2026-10");
  });

  it("parseMonth refuses a month 13 and junk", () => {
    expect(parseMonth("2026-10")).toBe("2026-10");
    expect(parseMonth("2026-13")).toBeNull();
    expect(parseMonth("2026-00")).toBeNull();
    expect(parseMonth("junk")).toBeNull();
    expect(parseMonth("2026-1")).toBeNull();
    expect(parseMonth(undefined)).toBeNull();
  });
});

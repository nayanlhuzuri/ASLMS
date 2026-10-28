/** Browser sorting with the server's rules (design list-search, decisions 29, 35 and 37). */
import { describe, expect, it } from "vitest";

import { compareCaseNumbers, compareDate, compareNumber, compareText, compareValues, dirWord, dirWords, nextSort, parseCaseNumber, sortRows } from "./sort";

describe("compareCaseNumbers", () => {
  it("orders by type, then number as a number, then year", () => {
    expect(compareCaseNumbers("WP(C) 9/2025", "WP(C) 10/2025")).toBeLessThan(0);
    expect(compareCaseNumbers("WP(C) 9/2024", "WP(C) 9/2025")).toBeLessThan(0);
    expect(compareCaseNumbers("WA 1/2024", "WP(C) 1/2024")).toBeLessThan(0);
  });

  it("reads WP(C)/9/2025 as WP(C) 9/2025", () => {
    expect(parseCaseNumber("WP(C)/9/2025")).toEqual({ type: "WP(C)", no: 9, year: 2025 });
    expect(compareCaseNumbers("WP(C)/9/2025", "WP(C) 9/2025")).toBe(0);
  });

  it("puts text that does not parse after parsed numbers, in natural order", () => {
    expect(compareCaseNumbers("Filing 12", "WP(C) 9/2025")).toBeGreaterThan(0);
    expect(compareCaseNumbers("Filing 2", "Filing 10")).toBeLessThan(0);
  });

  it("puts blanks last in both directions", () => {
    const rows = ["WP(C) 10/2025", "", "WP(C) 9/2025", null];
    expect(sortRows(rows, (r) => r, "caseNo", "asc")).toEqual(["WP(C) 9/2025", "WP(C) 10/2025", "", null]);
    expect(sortRows(rows, (r) => r, "caseNo", "desc")).toEqual(["WP(C) 10/2025", "WP(C) 9/2025", "", null]);
  });
});

describe("the comparators", () => {
  it("compareText ignores case and accents and orders numbers inside text naturally", () => {
    expect(compareText("revenue", "Revenue")).toBe(0);
    expect(compareText("Département", "departement")).toBe(0);
    expect(compareText("Court 2", "Court 10")).toBeLessThan(0);
  });

  it("compareDate and compareNumber compare by type, blanks last", () => {
    expect(compareDate("2025-10-02", "2025-10-12")).toBeLessThan(0);
    expect(compareDate("2025-10-12T05:00:00Z", "2025-10-12T04:00:00Z")).toBeGreaterThan(0);
    expect(compareNumber(9, 10)).toBeLessThan(0);
    expect(compareValues("number", null, 3, "asc")).toBeGreaterThan(0);
    expect(compareValues("number", null, 3, "desc")).toBeGreaterThan(0);
    expect(compareValues("date", "2025-01-01", undefined, "desc")).toBeLessThan(0);
  });

  it("the sort is stable: equal values keep the API's order", () => {
    const rows = [
      { id: 1, v: "b" },
      { id: 2, v: "a" },
      { id: 3, v: "b" },
      { id: 4, v: "a" },
    ];
    expect(sortRows(rows, (r) => r.v, "text", "asc").map((r) => r.id)).toEqual([2, 4, 1, 3]);
    expect(sortRows(rows, (r) => r.v, "text", "desc").map((r) => r.id)).toEqual([1, 3, 2, 4]);
  });
});

describe("direction words and the three-click cycle", () => {
  it("names each direction in Title Case by type", () => {
    expect(dirWords("text")).toEqual(["A to Z", "Z to A"]);
    expect(dirWords("number")).toEqual(["Lowest First", "Highest First"]);
    expect(dirWords("date")).toEqual(["Oldest First", "Newest First"]);
    expect(dirWords("date", "asc")).toEqual(["Earliest First", "Latest First"]);
    expect(dirWords("caseNo")).toEqual(["In Number Order", "Reverse Number Order"]);
    expect(dirWord("number", "desc", "desc", ["Fewest First", "Most First"])).toBe("Most First");
  });

  it("cycles the first direction, the other, then the default", () => {
    const first = nextSort(null, "next", "asc");
    expect(first).toEqual({ key: "next", dir: "asc" });
    const second = nextSort(first, "next", "asc");
    expect(second).toEqual({ key: "next", dir: "desc" });
    expect(nextSort(second, "next", "asc")).toBeNull();
    expect(nextSort(second, "other", "desc")).toEqual({ key: "other", dir: "desc" });
  });
});

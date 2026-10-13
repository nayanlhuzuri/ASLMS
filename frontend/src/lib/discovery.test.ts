import { describe, expect, it } from "vitest";

import { isDiscoverable, normaliseTerm, parseYears } from "./discovery";

describe("isDiscoverable (the server's rule, design department-discovery decision 1)", () => {
  it("accepts names after normalising, never a regex", () => {
    expect(normaliseTerm("  Dr.  R. Das ")).toBe("DR R DAS");
    expect(isDiscoverable("Pritam Saikia")).toBe(true);
    expect(isDiscoverable("M/S S.K. & Co (P) Ltd-1", "prefix")).toBe(true);
    expect(isDiscoverable("Pritam Saikia", "regex")).toBe(false);
  });

  it("refuses short, long and unsafe texts", () => {
    expect(isDiscoverable("AB")).toBe(false);
    expect(isDiscoverable("A".repeat(201))).toBe(false);
    expect(isDiscoverable("A|B=C")).toBe(false);
    expect(isDiscoverable("100%")).toBe(false);
  });
});

describe("parseYears", () => {
  it("reads years, lists and ranges, newest first", () => {
    expect(parseYears("2010", 2026)).toEqual([2010]);
    expect(parseYears("2010, 2012-2014", 2026)).toEqual([2014, 2013, 2012, 2010]);
    expect(parseYears("2014-2012 2012", 2026)).toEqual([2014, 2013, 2012]);
  });

  it("refuses bad parts, years out of range and more than 30", () => {
    expect(parseYears("", 2026)).toBeNull();
    expect(parseYears("twenty", 2026)).toBeNull();
    expect(parseYears("1949", 2026)).toBeNull();
    expect(parseYears("2027", 2026)).toBeNull();
    expect(parseYears("1990-2020", 2026)).toBeNull();
  });
});

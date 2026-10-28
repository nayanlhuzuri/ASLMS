/** The browser match of a list search (design list-search, decisions 3 and 8). */
import { describe, expect, it } from "vitest";

import { formatDate } from "./format";
import { LIST_SEARCH_FROM, matchesWords, searchShown } from "./listSearch";

describe("matchesWords", () => {
  it("needs every word in one of the texts", () => {
    expect(matchesWords("ram edu", "Ram Kumar", "EDU")).toBe(true);
    expect(matchesWords("ram health", "Ram Kumar", "EDU")).toBe(false);
    expect(matchesWords("", "anything")).toBe(true);
    expect(matchesWords("   ", null, undefined)).toBe(true);
  });

  it("ignores case and accents", () => {
    expect(matchesWords("DEPARTEMENT", "Département de l'éducation")).toBe(true);
    expect(matchesWords("éducation", "EDUCATION")).toBe(true);
  });

  it("finds dates in the portal's format", () => {
    const shown = formatDate("2025-10-12");
    expect(shown).toBe("12 Oct 2025");
    expect(matchesWords("12 oct", "SC, EDU", shown)).toBe(true);
    expect(matchesWords("13 oct", "SC, EDU", shown)).toBe(false);
  });
});

describe("searchShown", () => {
  it("hides the box at 10 rows and shows it at 11 or with a search set", () => {
    expect(LIST_SEARCH_FROM).toBe(10);
    expect(searchShown(10, "")).toBe(false);
    expect(searchShown(11, "")).toBe(true);
    expect(searchShown(3, "ram")).toBe(true);
    expect(searchShown(undefined, "")).toBe(false);
  });
});

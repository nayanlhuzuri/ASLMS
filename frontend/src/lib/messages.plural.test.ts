/**
 * Plurals and counts in the message catalogue (design portal-ui-kit-fixes, decisions 23 and 30): no "(s)" after a word,
 * every count in the Indian grouping, one word for one and another for many.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { plural as fromDigits } from "./digits";
import { formatNumber, plural } from "./format";
import { LABEL_FUNCTIONS } from "./labelRules";
import { T } from "./messages";

const SOURCE = readFileSync(join(process.cwd(), "src", "lib", "messages.ts"), "utf-8");

describe("plural", () => {
  it("writes the count grouped and the word for one or many", () => {
    expect(plural(0, "case", "cases")).toBe("0 cases");
    expect(plural(1, "case", "cases")).toBe("1 case");
    expect(plural(123456, "case", "cases")).toBe("1,23,456 cases");
    expect(fromDigits(2, "page", "pages")).toBe("2 pages");
  });

  it("the grouping is formatNumber's", () => {
    for (const n of [0, 7, 999, 1000, 128400, 12345678, -1234, 1234.5]) expect(plural(n, "x", "x")).toBe(`${formatNumber(n)} x`);
  });
});

describe("the catalogue's counts", () => {
  it("has no (s) after a word", () => {
    expect(SOURCE).not.toMatch(/[A-Za-z]\(s\)/);
  });

  it("formats the counts that were printed bare", () => {
    expect(T.discovery.ruleLine("1 Oct 2026", 123456)).toContain("1,23,456 cases found");
    expect(T.discovery.ruleLine("1 Oct 2026", 1)).toContain("1 case found");
    expect(T.offices.users(1234)).toBe("1,234 users");
    expect(T.offices.users(1)).toBe("1 user");
    expect(T.system.courtCount(1234, 12345)).toBe("1,234 of 12,345 working");
  });

  it("the former (s) messages read in words", () => {
    expect(T.case.pages(12)).toBe("12 pages");
    expect(T.case.pages(1)).toBe("1 page");
    expect(T.exit.counts(3, 1, 0, 2)).toBe("3 assigned cases, 1 case with them, 0 drafts, 2 open alerts");
    expect(T.wf.attachHint(5)).toBe("Up to 5 files; each is checked for viruses before it is stored.");
    expect(T.wf.tooManyFiles(1)).toBe("At most 1 file may be attached.");
  });

  it("the hand-written plurals group their numbers", () => {
    expect(T.shell.alerts(1200)).toBe("1,200 unread alerts");
    expect(T.access.users(1)).toBe("1 user");
    expect(T.access.unsaved(0)).toBe("No unsaved changes");
    expect(T.access.leaveText(1)).toBe("1 change is not saved and will be lost.");
    expect(T.access.leaveText(1500)).toBe("1,500 changes are not saved and will be lost.");
  });

  it("a count that is a label is in LABEL_FUNCTIONS", () => {
    expect(LABEL_FUNCTIONS).toHaveProperty(["dc.requestWhat.cases"]);
  });
});

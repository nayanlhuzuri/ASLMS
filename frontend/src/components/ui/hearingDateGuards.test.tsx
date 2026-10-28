/**
 * Extra proofs for next-hearing-highlight: impossible calendar dates, a leap day, every screen of decision 11 using
 * the kit badge, and the retired helpers staying gone.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hearingBand, hearingWords } from "@/lib/hearingDate";

import { HearingDate } from "./index";

const SRC = join(process.cwd(), "src");
const NOW = new Date("2026-10-27T06:30:00Z");

function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(n) && !/\.test\./.test(n)) out.push(p);
  }
  return out;
}

describe("hearing date edges", () => {
  it("treats an impossible calendar day as no date, not a band", () => {
    expect(hearingBand("2026-02-30", { now: NOW }).band).toBe("none");
    expect(hearingBand("2026-04-31", { now: NOW }).band).toBe("none");
  });

  it("counts a leap day", () => {
    const now = new Date("2028-02-28T06:30:00Z");
    expect(hearingBand("2028-02-29", { now })).toEqual({ band: "tomorrow", days: 1 });
    expect(hearingBand("2028-03-01", { now })).toEqual({ band: "week", days: 2 });
  });

  it("a suggested passed date still reads Suggested first with Date Passed", () => {
    expect(hearingWords("passed", -3, { kind: "suggested" })).toBe("Suggested · Date Passed");
  });

  it("a suggested later date in the small size reads Suggested alone, with the date shown", () => {
    const { container } = render(<HearingDate date="2026-11-16" kind="suggested" now={NOW} />);
    expect(container.querySelector("[data-kind='suggested']")).toHaveTextContent("Suggested");
    expect(container.querySelector("time")).toHaveAttribute("dateTime", "2026-11-16");
  });

  it("a disposed case shows no date element and a suggested kind is ignored without a date", () => {
    const { container } = render(<HearingDate date="2026-10-28" status="disposed" kind="suggested" now={NOW} />);
    expect(container.querySelector("time")).toBeNull();
    expect(container.querySelector("[data-kind]")).toHaveAttribute("data-kind", "firm");
  });

  it("showDate off drops the time element in every band", () => {
    for (const d of ["2026-10-27", "2026-10-28", "2026-10-30", "2026-11-16", "2026-10-22"]) {
      const { container } = render(<HearingDate date={d} showDate={false} now={NOW} />);
      expect(container.querySelector("time"), d).toBeNull();
      expect(container.textContent?.trim().length, d).toBeGreaterThan(0);
    }
  });
});

describe("screens and retired helpers", () => {
  const files = walk(SRC);
  const read = (rel: string) => readFileSync(join(SRC, rel), "utf-8");

  it.each([
    "components/case/CaseFrame.tsx",
    "components/case/Rail.tsx",
    "components/claim/CaseModal.tsx",
    "components/claim/Pool.tsx",
    "components/claim/Recommended.tsx",
    "components/dashboard/Blocks.tsx",
    "components/dashboard/Headline.tsx",
    "components/inbox/DepartmentCases.tsx",
    "components/inbox/MyCases.tsx",
    "components/inbox/WorkingOn.tsx",
    "components/nextdates/CaseNextDate.tsx",
    "components/search/CaseResults.tsx",
  ])("%s renders the kit HearingDate", (rel) => {
    expect(read(rel)).toMatch(/<HearingDate\b|HearingDate\s*,|HearingDate\s*}/);
  });

  it("no source file defines or calls a retired helper", () => {
    const stale = /\b(hearingBadge|hearingCountdown|dayWords|NextHearingCell|within48)\b/;
    const hits = files.filter((f) => stale.test(readFileSync(f, "utf-8"))).map((f) => f.replace(SRC, ""));
    expect(hits).toEqual([]);
  });

  it("HearingDate never reads the browser zone or an hour", () => {
    const src = readFileSync(join(SRC, "lib/hearingDate.ts"), "utf-8");
    expect(src).not.toMatch(/getTimezoneOffset|getHours|toLocale|Intl\./);
  });
});

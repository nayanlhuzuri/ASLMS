import { describe, expect, it } from "vitest";

import type { CauselistBench } from "./api/types";
import {
  bandLabel,
  benchesWithLists,
  benchParams,
  benchPdfState,
  benchValue,
  benchValueOf,
  causelistHref,
  ENTRY_PAGE,
  headingsOf,
  listsById,
  recommendationText,
  toApiQuery,
  validDate,
  type HeadingSource,
} from "./causelist";

const LIST = "01a134e4-0231-7a65-9193-28fe67e22fb5";

describe("toApiQuery", () => {
  it("passes the URL's keys with their API names and the page", () => {
    expect(
      toApiQuery({ date: "2026-10-13", bench_id: "1854", list_type: "Daily", court_no: " 10 ", q: " anima ", only: "mine", offset: "200" }),
    ).toEqual({
      bench_id: "1854",
      list_id: undefined,
      list_type: "daily",
      court_no: "10",
      q: "anima",
      only: "mine",
      limit: ENTRY_PAGE,
      offset: 200,
    });
  });

  it("drops unknown values, short words and a list id next to a bench", () => {
    expect(toApiQuery({ bench_id: "x", list_id: LIST, list_type: "weekly", only: "all", q: "ab", offset: "-3" })).toEqual({
      bench_id: undefined,
      list_id: LIST,
      list_type: undefined,
      court_no: undefined,
      q: undefined,
      only: undefined,
      limit: ENTRY_PAGE,
      offset: 0,
    });
    expect(toApiQuery({ bench_id: "7", list_id: LIST }).list_id).toBeUndefined();
  });

  it("valid dates only", () => {
    expect(validDate("2026-10-13")).toBe("2026-10-13");
    expect(validDate("13-10-2026")).toBeUndefined();
    expect(validDate(undefined)).toBeUndefined();
  });
});

function e(court: string | null, bench: number | null, list: string, section: string | null): HeadingSource {
  return { court_no: court, bench_id: bench, bench_label: bench ? `BENCH ${bench}` : null, causelist_id: list, list_type: "daily", section };
}

const TEXTS = {
  court: (c: string | null) => (c ? `Court ${c}` : "No court"),
  bench: (label: string | null, id: number | null) => label ?? (id ? `Bench ${id}` : "Court-wide"),
  list: (t: string) => `${t} list`,
};

describe("headingsOf", () => {
  it("draws every level first, then from the level that changes down", () => {
    const items = [
      e("2", 777, "l1", "ORDERS"),
      e("10", 1854, "l2", "ORDERS"),
      e("10", 1854, "l2", "ORDERS"),
      e("10", 1854, "l2", "FOR ADMISSION"),
      e("10", 1854, "l3", "ORDERS"),
      e("10", 1854, "l3", null),
      e(null, null, "l4", null),
    ];
    const out = headingsOf(items, TEXTS).map((hs) => hs.map((h) => `${h.kind}:${h.text}`));
    expect(out).toEqual([
      ["court:Court 2", "bench:BENCH 777", "list:daily list", "section:ORDERS"],
      ["court:Court 10", "bench:BENCH 1854", "list:daily list", "section:ORDERS"],
      [],
      ["section:FOR ADMISSION"],
      ["list:daily list", "section:ORDERS"],
      [],
      ["court:No court", "bench:Court-wide", "list:daily list"],
    ]);
  });
});

describe("labels", () => {
  it("bands and recommendation badges come from the API's band", () => {
    expect(bandLabel("high")).toBe("Strong");
    expect(bandLabel("medium")).toBe("Possible");
    expect(recommendationText({ office_code: "EDU", band: "high", score: 0.95 })).toBe("Strong · EDU · 0.95");
  });

  it("bench values, URL keys and the case page's link", () => {
    const napix = { bench_id: 1854, lists: [] } as unknown as CauselistBench;
    const website = { bench_id: null, lists: [{ id: LIST }] } as unknown as CauselistBench;
    expect(benchValue(napix)).toBe("b:1854");
    expect(benchValue(website)).toBe(`l:${LIST}`);
    expect(benchParams("b:1854")).toEqual({ bench_id: "1854", list_id: undefined });
    expect(benchParams(`l:${LIST}`)).toEqual({ bench_id: undefined, list_id: LIST });
    expect(benchParams("")).toEqual({ bench_id: undefined, list_id: undefined });
    expect(benchValueOf({ list_id: LIST })).toBe(`l:${LIST}`);
    expect(causelistHref("2026-10-13", 1854)).toBe("/causelist?date=2026-10-13&bench_id=1854");
    expect(causelistHref("2026-10-20", null)).toBe("/causelist?date=2026-10-20");
  });
});

describe("the original PDF without a bench (causelist-pdf-access)", () => {
  const l = (id: string, has_pdf: boolean, fetch_status: string) => ({ id, has_pdf, fetch_status }) as unknown as CauselistBench["lists"][number];
  const a = { bench_id: 1, lists: [l("a1", true, "fetched"), l("a2", false, "pending")] } as unknown as CauselistBench;
  const b = { bench_id: 2, lists: [] } as unknown as CauselistBench;
  const c = { bench_id: null, lists: [l("c1", false, "pending")] } as unknown as CauselistBench;
  const d = { bench_id: 4, lists: [l("d1", false, "pending"), l("d2", false, "not_available")] } as unknown as CauselistBench;

  it("benchesWithLists keeps the benches with a list, in the given order", () => {
    expect(benchesWithLists([a, b, c, d])).toEqual([a, c, d]);
    expect(benchesWithLists([b])).toEqual([]);
  });

  it("listsById indexes every list of the day", () => {
    const out = listsById([a, b, c]);
    expect(Object.keys(out).sort()).toEqual(["a1", "a2", "c1"]);
    expect(out.c1).toBe(c.lists[0]);
  });

  it("benchPdfState: available, pending, none", () => {
    expect(benchPdfState(a)).toBe("available");
    expect(benchPdfState(c)).toBe("pending");
    expect(benchPdfState(d)).toBe("none");
    expect(benchPdfState(b)).toBe("none");
  });
});

import { describe, expect, it } from "vitest";

import {
  chipsOf,
  dateModeOf,
  dateParams,
  hasCaseFilter,
  legacyParams,
  resolveDates,
  toApiQuery,
  validate,
  type ChipTexts,
} from "./filters";

// 00:30 IST on 14 Oct 2026 is still 13 Oct in UTC: the presets follow the IST day
const NEAR_MIDNIGHT = new Date("2026-10-13T19:00:00Z");

const TEXTS = { reversed: "reversed", chooseDate: "choose", year: "year", words: "words", bench: "bench" };

const CHIPS: ChipTexts = {
  field: {
    q: "Words",
    listed: "Cause list",
    next: "Next hearing",
    case_type: "Case type",
    year: "Year",
    case_status: "Status",
    court_no: "Court",
    bench: "Bench",
    owner: "Department",
    scored_for: "Matched to department",
    other_office: "Other department",
  },
  listedPresets: { today: "Today", tomorrow: "Tomorrow", d7: "Last 7 days", d30: "Last 30 days" },
  nextPresets: { today: "Today", n7: "Next 7 days", n30: "Next 30 days" },
  statuses: { pending: "Pending", disposed: "Disposed", unknown: "Unknown" },
  range: (a, b) => `${a} – ${b}`,
  from: (d) => `from ${d}`,
  to: (d) => `to ${d}`,
};

describe("resolveDates (decision 10)", () => {
  it("resolves the cause-list presets in IST near midnight", () => {
    expect(resolveDates({ listed: "today" }, NEAR_MIDNIGHT)).toEqual({ listed_from: "2026-10-14", listed_to: "2026-10-14" });
    expect(resolveDates({ listed: "tomorrow" }, NEAR_MIDNIGHT)).toEqual({
      listed_from: "2026-10-15",
      listed_to: "2026-10-15",
    });
    expect(resolveDates({ listed: "d7" }, NEAR_MIDNIGHT)).toEqual({ listed_from: "2026-10-08", listed_to: "2026-10-14" });
    expect(resolveDates({ listed: "d30" }, NEAR_MIDNIGHT)).toEqual({ listed_from: "2026-09-15", listed_to: "2026-10-14" });
  });

  it("resolves the next-hearing presets in IST near midnight", () => {
    expect(resolveDates({ next: "today" }, NEAR_MIDNIGHT)).toEqual({ next_from: "2026-10-14", next_to: "2026-10-14" });
    expect(resolveDates({ next: "n7" }, NEAR_MIDNIGHT)).toEqual({ next_from: "2026-10-14", next_to: "2026-10-20" });
    expect(resolveDates({ next: "n30" }, NEAR_MIDNIGHT)).toEqual({ next_from: "2026-10-14", next_to: "2026-11-12" });
  });

  it("explicit dates win over a preset; an unknown preset is no filter", () => {
    expect(resolveDates({ listed: "today", listed_from: "2026-09-01" }, NEAR_MIDNIGHT)).toEqual({
      listed_from: "2026-09-01",
    });
    expect(resolveDates({ next: "n7", next_to: "2026-12-31" }, NEAR_MIDNIGHT)).toEqual({ next_to: "2026-12-31" });
    expect(resolveDates({ listed: "yesterday", next: "d7" }, NEAR_MIDNIGHT)).toEqual({});
  });
});

describe("toApiQuery (decision 11)", () => {
  const ALL = {
    q: "ram kumar",
    listed: "today",
    next_from: "2026-10-20",
    case_type: "WP(C)",
    year: "2025",
    case_status: "pending",
    court_no: "3",
    bench: "SAIKIA",
    owner: "FIN",
    scored_for: "EDU",
    other_office: "HEALTH",
  };

  it("sends only the fields the list allows", () => {
    const rec = toApiQuery(ALL, "recommended", NEAR_MIDNIGHT);
    expect(rec).toEqual({
      q: "ram kumar",
      listed_from: "2026-10-14",
      listed_to: "2026-10-14",
      next_from: "2026-10-20",
      case_type: "WP(C)",
      year: "2025",
      case_status: "pending",
      court_no: "3",
      bench: "SAIKIA",
    });
    expect(rec).not.toHaveProperty("owner");
    expect(toApiQuery(ALL, "pool", NEAR_MIDNIGHT)).toMatchObject({ scored_for: "EDU" });
    expect(toApiQuery(ALL, "pool", NEAR_MIDNIGHT)).not.toHaveProperty("owner");
    expect(toApiQuery(ALL, "transfers", NEAR_MIDNIGHT)).toMatchObject({ other_office: "HEALTH" });
    expect(toApiQuery(ALL, "transfers", NEAR_MIDNIGHT)).not.toHaveProperty("scored_for");
    expect(toApiQuery(ALL, "held", NEAR_MIDNIGHT)).toMatchObject({ owner: "FIN" });
    expect(toApiQuery(ALL, "alerts", NEAR_MIDNIGHT)).not.toHaveProperty("other_office");
    const disposed = toApiQuery(ALL, "claimed_disposed", NEAR_MIDNIGHT);
    expect(disposed).not.toHaveProperty("next_from");
    expect(disposed).not.toHaveProperty("case_status");
    expect(toApiQuery(ALL, "documents", NEAR_MIDNIGHT)).toEqual({ q: "ram kumar" });
  });

  it("leaves out empty values", () => {
    expect(toApiQuery({ q: " ", year: "" }, "search")).toEqual({});
  });
});

describe("legacyParams (decision 13)", () => {
  it("maps status and office on Search, status on the pool, nothing elsewhere", () => {
    expect(legacyParams({ status: "disposed", office: "FIN" }, "search")).toEqual({ case_status: "disposed", owner: "FIN" });
    expect(toApiQuery({ status: "disposed", office: "FIN" }, "search")).toEqual({ case_status: "disposed", owner: "FIN" });
    expect(legacyParams({ status: "disposed", office: "FIN" }, "pool")).toEqual({ case_status: "disposed", office: "FIN" });
    expect(legacyParams({ status: "requested" }, "transfers")).toEqual({ status: "requested" });
    expect(legacyParams({ status: "open" }, "alerts")).toEqual({ status: "open" });
    // a new key already present wins
    expect(legacyParams({ status: "disposed", case_status: "pending" }, "search")).toEqual({ case_status: "pending" });
  });
});

describe("validate (decision 7)", () => {
  it("refuses a reversed range, a 3-digit year and a 2-character word", () => {
    expect(validate({ listed: { mode: "range", from: "2026-10-02", to: "2026-10-01" } }, TEXTS)).toEqual({
      listed_to: "reversed",
    });
    expect(validate({ next: { mode: "range", from: "2026-11-02", to: "2026-11-01" } }, TEXTS)).toEqual({
      next_to: "reversed",
    });
    expect(validate({ year: "202" }, TEXTS)).toEqual({ year: "year" });
    expect(validate({ year: "1899" }, TEXTS)).toEqual({ year: "year" });
    expect(validate({ q: "ab" }, TEXTS)).toEqual({ q: "words" });
    expect(validate({ bench: " ab " }, TEXTS)).toEqual({ bench: "bench" });
    expect(validate({ listed: { mode: "date", from: "", to: "" } }, TEXTS)).toEqual({ listed_from: "choose" });
    expect(validate({ ranges: [{ key: "date_to", from: "2026-02-01", to: "2026-01-01" }] }, TEXTS)).toEqual({
      date_to: "reversed",
    });
  });

  it("accepts good values and open-ended ranges", () => {
    expect(
      validate(
        {
          q: "WP(C) 4326/2025",
          year: "2025",
          bench: "SAIKIA",
          listed: { mode: "range", from: "2026-10-01", to: "" },
          next: { mode: "n7", from: "", to: "" },
        },
        TEXTS,
      ),
    ).toEqual({});
  });
});

describe("the date field and chips", () => {
  it("reads and writes the date modes", () => {
    expect(dateModeOf({ listed_from: "2026-10-01", listed_to: "2026-10-01" }, "listed").mode).toBe("date");
    expect(dateModeOf({ listed_from: "2026-10-01", listed_to: "2026-10-07" }, "listed").mode).toBe("range");
    expect(dateModeOf({ next: "n30" }, "next").mode).toBe("n30");
    expect(dateModeOf({ next: "d7" }, "next").mode).toBe("");
    expect(dateParams("listed", "date", "2026-10-01", "")).toEqual({
      listed: undefined,
      listed_from: "2026-10-01",
      listed_to: "2026-10-01",
    });
    expect(dateParams("next", "n7", "", "")).toEqual({ next: "n7", next_from: undefined, next_to: undefined });
  });

  it("makes a chip for every field", () => {
    const chips = chipsOf(
      {
        q: "ram",
        listed_from: "2026-09-25",
        listed_to: "2026-09-25",
        next: "n7",
        case_type: "WP(C)",
        year: "2025",
        case_status: "disposed",
        court_no: "3",
        bench: "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA",
        owner: "FIN",
      },
      "search",
      CHIPS,
    );
    expect(chips.map((c) => c.label)).toEqual([
      "Words: ram",
      "Cause list: 25 Sep 2026",
      "Next hearing: Next 7 days",
      "Case type: WP(C)",
      "Year: 2025",
      "Status: Disposed",
      "Court: 3",
      "Bench: HONOURABLE MR. JUSTICE SOUMITRA SAIKIA",
      "Department: FIN",
    ]);
    expect(chips[1]!.keys).toEqual(["listed", "listed_from", "listed_to"]);
    const range = chipsOf({ listed_from: "2026-10-01", listed_to: "2026-10-07", scored_for: "EDU" }, "pool", CHIPS);
    expect(range.map((c) => c.label)).toEqual(["Cause list: 1 Oct 2026 – 7 Oct 2026", "Matched to department: EDU"]);
    // a chip read from an old name also drops it
    expect(chipsOf({ status: "disposed" }, "search", CHIPS)[0]!.keys).toEqual(["case_status", "status"]);
    expect(chipsOf({ other_office: "FIN" }, "transfers", CHIPS)[0]!.label).toBe("Other department: FIN");
  });

  it("tells whether a case filter is set", () => {
    expect(hasCaseFilter({ status: "all", kind: "workflow" }, "alerts")).toBe(false);
    expect(hasCaseFilter({ year: "2025" }, "alerts")).toBe(true);
    expect(hasCaseFilter({ listed: "today" }, "alerts")).toBe(true);
  });
});

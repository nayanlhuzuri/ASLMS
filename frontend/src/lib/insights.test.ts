import { describe, expect, it } from "vitest";

import {
  bandToggled,
  chartSummary,
  chipRemoved,
  clearedAll,
  datesOutOfOrder,
  datesSet,
  exportHref,
  filterQuery,
  headlineClicked,
  headlineSelected,
  holderToggled,
  insightsHref,
  insightsParams,
  monthRange,
  quickDated,
  saveFields,
  savedFields,
  shortLabel,
  tickLabel,
  toggled,
  trendClicked,
  viewSet,
} from "./insights";

describe("the Insights address (design state-insights, decisions 24 and 32)", () => {
  it("keeps only the API's parameters, in a stable order, and drops empty ones", () => {
    expect(insightsParams({ junk: "x", kind: "contempt", scope: "state", page: "2", next: "" })).toEqual({
      scope: "state",
      kind: "contempt",
      page: "2",
    });
    expect(insightsHref({ kind: "contempt", next: "within_7" })).toBe("/insights?kind=contempt&next=within_7");
    expect(filterQuery({ kind: "wp", page: "3", sort: "registered", from: "2026-01-01" })).toEqual({ kind: "wp", from: "2026-01-01" });
  });

  it("a click sets a dimension and a second click on the same value removes it; any change goes back to page 1", () => {
    const once = toggled({ page: "4" }, "kind", "contempt");
    expect(once).toEqual({ kind: "contempt" });
    expect(toggled(once, "kind", "contempt")).toEqual({});
    expect(toggled(once, "kind", "wp")).toEqual({ kind: "wp" });
  });

  it("a department band sets dept and band together, the same pair again removes both", () => {
    const set = bandToggled({}, "EDU", "likely");
    expect(set).toEqual({ dept: "EDU", band: "likely" });
    expect(bandToggled(set, "EDU", "likely")).toEqual({});
    expect(bandToggled(set, "EDU", "claimed")).toEqual({ dept: "EDU", band: "claimed" });
    expect(bandToggled(set, "EDU", null)).toEqual({ dept: "EDU" });
    expect(toggled(set, "dept", "HEALTH")).toEqual({ dept: "HEALTH" });
  });

  it("a holder sets holder and action=overdue as two filters; the same holder again removes the holder only", () => {
    const set = holderToggled({}, "EDU-DSE");
    expect(set).toEqual({ holder: "EDU-DSE", action: "overdue" });
    expect(holderToggled(set, "EDU-DSE")).toEqual({ action: "overdue" });
  });

  it("removing a chip takes its companions; Clear All keeps the view, the switch and the toggles", () => {
    const p = { scope: "state", status: "all", state_only: "false", kind: "wp", dept: "EDU", band: "named", date_of: "registration", from: "2026-01-01", to: "2026-02-01" };
    expect(chipRemoved(p, "dept")).not.toHaveProperty("band");
    const noDates = chipRemoved(p, "date_of");
    for (const k of ["date_of", "from", "to"]) expect(noDates).not.toHaveProperty(k);
    expect(clearedAll(p)).toEqual({ scope: "state", status: "all", state_only: "false" });
  });

  it("a view change drops filters that belong to the other scope", () => {
    expect(viewSet({ scope: "state", dept: "EDU", band: "likely", unit: "X" }, "scope", "department")).toEqual({ scope: "department" });
    expect(viewSet({ status: "all" }, "status", null)).toEqual({});
  });

  it("the headline figures set their filters, and Cases sets none", () => {
    expect(headlineClicked({}, "contempt")).toEqual({ kind: "contempt" });
    expect(headlineClicked({ kind: "contempt" }, "contempt")).toEqual({});
    expect(headlineClicked({}, "over_5_years")).toEqual({ age: "over_5" });
    expect(headlineClicked({}, "hearing_7_days")).toEqual({ next: "within_7" });
    expect(headlineClicked({}, "not_claimed")).toEqual({ action: "not_claimed" });
    expect(headlineClicked({ state_only: "false" }, "state_cases")).toEqual({});
    expect(headlineClicked({}, "cases")).toBeNull();
    expect(headlineSelected({ next: "within_7" }, "hearing_7_days")).toBe(true);
    expect(headlineSelected({}, "state_cases")).toBe(true);
    expect(headlineSelected({ state_only: "false" }, "state_cases")).toBe(false);
  });

  it("a month of the trend sets Date Of to that month; the same month again clears the dates", () => {
    expect(monthRange("2026-02")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    const set = trendClicked({}, "2026-10", "registration");
    expect(set).toEqual({ date_of: "registration", from: "2026-10-01", to: "2026-10-31" });
    expect(trendClicked(set, "2026-10", "registration")).toEqual({});
    expect(trendClicked(set, "2026-10", "disposal")).toMatchObject({ date_of: "disposal" });
  });

  it("the quick dates fill Date Of, From and To", () => {
    const today = "2026-11-19";
    expect(quickDated({}, "last_30", today)).toEqual({ date_of: "registration", from: "2026-10-20", to: today });
    expect(quickDated({ date_of: "disposal" }, "this_year", today)).toEqual({ date_of: "disposal", from: "2026-01-01", to: today });
    expect(quickDated({}, "next_7", today)).toEqual({ date_of: "next_hearing", from: today, to: "2026-11-26" });
    expect(quickDated({}, "next_30", today)).toEqual({ date_of: "next_hearing", from: today, to: "2026-12-19" });
    expect(quickDated({ date_of: "registration", from: "a", to: "b", kind: "wp" }, "clear", today)).toEqual({ kind: "wp" });
  });

  it("the date bar applies the three together and refuses From after To", () => {
    expect(datesSet({}, "latest_order", "2026-01-01", "")).toEqual({ date_of: "latest_order", from: "2026-01-01" });
    expect(datesSet({ date_of: "registration", from: "x" }, "registration", "", "")).toEqual({});
    expect(datesOutOfOrder("2026-02-01", "2026-01-01")).toBe(true);
    expect(datesOutOfOrder("2026-01-01", "")).toBe(false);
  });
});

describe("the export address and the kept fields (decisions 27 and 33)", () => {
  it("carries exactly the filters, the sort, the format and the fields", () => {
    expect(exportHref({ kind: "contempt", page: "3" }, "pdf", ["case_no", "cnr"], "registered")).toBe(
      "/api/backend/insights/export?kind=contempt&sort=registered&format=pdf&fields=case_no%2Ccnr",
    );
  });

  it("keeps the choice in the browser and ignores anything unreadable", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(savedFields(storage)).toBeNull();
    saveFields(["case_no", "status"], storage);
    expect(savedFields(storage)).toEqual(["case_no", "status"]);
    store.set("aslms.insights.export", "{oops");
    expect(savedFields(storage)).toBeNull();
  });
});

describe("chart words (decision 31)", () => {
  it("the selected bar's label carries a tick; long labels are shortened", () => {
    expect(tickLabel("Contempt", true)).toBe("✓ Contempt");
    expect(tickLabel("Contempt", false)).toBe("Contempt");
    expect(shortLabel("Department of School Education, Government of Assam", 20)).toBe("Department of Schoo…");
  });

  it("the accessible summary names the buckets and their counts", () => {
    expect(chartSummary("Next Hearing", [{ label: "Today", count: 4 }, { label: "Tomorrow", count: 2 }], String)).toBe(
      "Next Hearing: Today 4, Tomorrow 2",
    );
    expect(chartSummary("Posts", [], String)).toBe("Posts: no cases");
  });
});

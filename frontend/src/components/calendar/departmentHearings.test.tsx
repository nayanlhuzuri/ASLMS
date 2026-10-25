import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CalendarItem } from "@/lib/api/types";
import { monthOf, shiftMonth, todayIst } from "@/lib/workflow";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { DepartmentHearings as Calendar } from "./DepartmentHearings";

const CASE = { id: "c1", ref_no: "ASLMS/GOA/CASE/2026/000001", cnr: null, case_no_text: "WP(C)/1/2026" };

function item(date: string, extra: Partial<CalendarItem> = {}): CalendarItem {
  return {
    case: CASE,
    date,
    court_no: "3",
    item_no: "14",
    purpose: "Admission",
    source: "causelist",
    critical: false,
    this_week: false,
    ...extra,
  };
}

const ITEMS: CalendarItem[] = [
  item("2026-10-14", { critical: true, this_week: true }),
  item("2026-10-14", { case: { ...CASE, id: "c2", case_no_text: "WA/2/2026" }, source: "next_date", this_week: true }),
  item("2026-10-14", { case: { ...CASE, id: "c3", case_no_text: "WA/3/2026" }, source: "current_status" }),
  item("2026-10-20", { case: { ...CASE, id: "c4", case_no_text: "WA/4/2026" }, source: "mystery" }),
];

function calendarCalls(calls: { path: string }[]) {
  return calls.filter((c) => c.path.startsWith("/calendar"));
}

beforeEach(() => {
  resetNav("/calendar");
});

describe("the hearing calendar (portal-files-alerts, decisions 10, 11)", () => {
  it("the default view asks for the API's default range and shows no grid", async () => {
    const api = browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: ITEMS } });
    renderWithClient(<Calendar params={{}} />);
    expect(await screen.findByRole("region", { name: "Agenda" })).toBeInTheDocument();
    expect(calendarCalls(api.calls).map((c) => c.path)).toEqual(["/calendar"]);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("button", { name: "Next 7 Days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a month asks for its first and last day, never more than 62 days, and shows the grid", async () => {
    const api = browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: ITEMS } });
    renderWithClient(<Calendar params={{ month: "2026-10" }} />);
    const grid = await screen.findByRole("table", { name: "October 2026" });
    const path = calendarCalls(api.calls)[0]!.path;
    expect(path).toBe("/calendar?from=2026-10-01&to=2026-10-31");
    const from = new Date("2026-10-01");
    const to = new Date("2026-10-31");
    expect((to.getTime() - from.getTime()) / 86_400_000).toBeLessThanOrEqual(62);
    const heads = within(grid).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    // October 2026 begins on a Thursday: three empty cells before the 1st
    const firstRow = within(grid).getAllByRole("row")[1]!;
    const cells = within(firstRow).getAllByRole("cell");
    expect(cells.slice(0, 3).every((c) => c.textContent === "")).toBe(true);
    expect(cells[3]!.textContent).toBe("1");
  });

  it("day cells show the count and the critical mark from the API's flags and link to the agenda", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: ITEMS } });
    renderWithClient(<Calendar params={{ month: "2026-10" }} />);
    const grid = await screen.findByRole("table", { name: "October 2026" });
    const day14 = within(grid).getByRole("link", { name: "14 October: 3 hearings, 1 within 48 hours" });
    expect(day14).toHaveAttribute("href", "#d-2026-10-14");
    expect(within(day14).getByText("3 hearings")).toBeInTheDocument();
    expect(within(day14).getByText("Within 48 Hours")).toBeInTheDocument();
    const day20 = within(grid).getByRole("link", { name: "20 October: 1 hearing" });
    expect(within(day20).queryByText("Within 48 Hours")).toBeNull();
    expect(document.getElementById("d-2026-10-14")).not.toBeNull();
  });

  it("the agenda shows the badges only from the flags, and the source labels", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: ITEMS } });
    renderWithClient(<Calendar params={{}} />);
    const agenda = await screen.findByRole("region", { name: "Agenda" });
    const row = (caseNo: string) => within(agenda).getByRole("link", { name: caseNo }).closest("li")!;
    expect(within(row("WP(C)/1/2026")).getByText("Within 48 Hours")).toBeInTheDocument();
    expect(within(row("WP(C)/1/2026")).getByText("This Week")).toBeInTheDocument();
    expect(within(row("WP(C)/1/2026")).getByText(/Cause List/)).toBeInTheDocument();
    expect(within(row("WA/2/2026")).queryByText("Within 48 Hours")).toBeNull();
    expect(within(row("WA/2/2026")).getByText(/Next Date/)).toBeInTheDocument();
    expect(within(row("WA/3/2026")).queryByText("This Week")).toBeNull();
    expect(within(row("WA/3/2026")).getByText(/Court Records/)).toBeInTheDocument();
    expect(within(row("WA/4/2026")).getByText(/mystery/)).toBeInTheDocument();
    // dates ascending
    const heads = within(agenda).getAllByRole("heading", { level: 3 }).map((h) => h.id);
    expect(heads).toEqual(["d-2026-10-14", "d-2026-10-20"]);
  });

  it("an empty range says so", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: [] } });
    renderWithClient(<Calendar params={{}} />);
    expect(await screen.findByText("No hearings in this period.")).toBeInTheDocument();
  });

  it("previous, next and this month change the query string", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: [] } });
    renderWithClient(<Calendar params={{ month: "2026-01" }} />);
    await screen.findByRole("table", { name: "January 2026" });
    await userEvent.click(screen.getByRole("button", { name: "Previous Month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?month=2025-12");
    await userEvent.click(screen.getByRole("button", { name: "Next Month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?month=2026-02");
    await userEvent.click(screen.getByRole("button", { name: "This Month" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/calendar?month=${monthOf(todayIst())}`);
    await userEvent.click(screen.getByRole("button", { name: "Next 7 Days" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar");
  });

  it("today is marked in the grid", async () => {
    const month = monthOf(todayIst());
    browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: [] } });
    renderWithClient(<Calendar params={{ month }} />);
    await screen.findByRole("table");
    const today = document.querySelector('[aria-current="date"]');
    expect(today?.textContent).toContain(String(Number(todayIst().slice(8))));
    expect(shiftMonth(month, 0)).toBe(month);
  });

  it("a State-wide reader chooses a department first; nothing is requested until then", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope", "cases.view_all"], "auditor", { memberships: [] }),
      "GET /custody/recipients": { departments: [{ code: "EDU", name: "Education" }], items: [], units: [], total: 1 },
      "GET /calendar": { items: ITEMS },
    });
    const { unmount } = renderWithClient(<Calendar params={{}} />);
    expect(await screen.findByText("Choose a department to see its hearings.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("option", { name: "EDU — Education" })).toBeInTheDocument());
    expect(calendarCalls(api.calls)).toHaveLength(0);
    await userEvent.selectOptions(screen.getByLabelText("Department"), "EDU");
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?department=EDU");
    unmount();
    renderWithClient(<Calendar params={{ department: "EDU" }} />);
    await screen.findByRole("region", { name: "Agenda" });
    expect(calendarCalls(api.calls).map((c) => c.path)).toEqual(["/calendar?office=EDU"]);
  });

  it("other readers never send office", async () => {
    const api = browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: [] } });
    renderWithClient(<Calendar params={{ department: "EDU" }} />);
    await screen.findByText("No hearings in this period.");
    expect(calendarCalls(api.calls).map((c) => c.path)).toEqual(["/calendar"]);
    expect(screen.queryByLabelText("Department")).toBeNull();
  });

  it("an unparseable month falls back to the default view", async () => {
    const api = browserApi({ "GET /me": makeMe(["cases.view_scope"]), "GET /calendar": { items: [] } });
    renderWithClient(<Calendar params={{ month: "2026-13" }} />);
    await screen.findByText("No hearings in this period.");
    expect(calendarCalls(api.calls).map((c) => c.path)).toEqual(["/calendar"]);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("bad_range shows the server's message", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /calendar": json(422, { detail: { code: "bad_range", message: "the range may span at most 62 days" } }),
    });
    renderWithClient(<Calendar params={{ month: "2026-10" }} />);
    expect(await screen.findByText("the range may span at most 62 days")).toBeInTheDocument();
  });
});

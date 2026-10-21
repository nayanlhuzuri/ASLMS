/**
 * My calendar (design portal-ui-redesign, decision 8; API A6): the three kinds in their tones, the legend that hides a
 * kind, today marked, Previous / Next month in the query string, a day's agenda with the badges in the fixed leading
 * column, accessible day names (the phone dots carry no text), the Department hearings switch only for
 * whole-department members and State-wide readers, and the `/alerts/calendar` redirect.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { MyCalendarItem, Permission } from "@/lib/api/types";
import { gridRange, gridWeeks, parseDay } from "@/lib/calendar";
import { monthOf, todayIst } from "@/lib/workflow";
import { nav, resetNav } from "@/test/nav";
import { browserApi, makeMe, renderWithClient } from "@/test/render";

import { CalendarRedirect } from "./CalendarRedirect";
import { MyCalendar } from "./MyCalendar";

const CASE = { id: "c1", ref_no: "ASLMS/GOA/CASE/2026/000001", cnr: null, case_no_text: "WP(C)/1/2026" };

function item(date: string, kind: MyCalendarItem["kind"], extra: Partial<MyCalendarItem> = {}): MyCalendarItem {
  return {
    date,
    kind,
    case: CASE,
    critical: false,
    court_no: null,
    item_no: null,
    purpose: null,
    source: null,
    this_week: null,
    pending_action: null,
    pending_action_label: null,
    overdue: null,
    next_date_id: null,
    ...extra,
  };
}

const ITEMS: MyCalendarItem[] = [
  item("2026-10-22", "hearing", { court_no: "3", item_no: "14", purpose: "Admission", source: "causelist" }),
  item("2026-10-22", "action_due", {
    case: { ...CASE, id: "c2", case_no_text: "WA/2/2026" },
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    overdue: false,
  }),
  item("2026-10-22", "confirm", { case: { ...CASE, id: "c3", case_no_text: "WA/3/2026" }, next_date_id: "nd-1", source: "order_period" }),
  item("2026-10-28", "hearing", { case: { ...CASE, id: "c4", case_no_text: "WA/4/2026" } }),
];

const OFFICER: Permission[] = ["cases.view_scope"];

function routes(functions: Permission[] = OFFICER, extra: Record<string, unknown> = {}) {
  return {
    "GET /me": makeMe(functions),
    "GET /me/calendar": { items: ITEMS },
    "GET /inbox/counts": { departments: [{ office_code: "EDU", whole_department: false }] },
    ...extra,
  };
}

beforeEach(() => resetNav("/calendar"));

describe("the month grid helpers", () => {
  it("runs from the Monday on or before the 1st to the Sunday on or after the last day", () => {
    const weeks = gridWeeks("2026-10");
    expect(weeks[0]![0]).toBe("2026-09-28");
    expect(weeks[weeks.length - 1]![6]).toBe("2026-11-01");
    expect(weeks.every((w) => w.length === 7)).toBe(true);
    expect(gridRange("2026-11")).toEqual({ from: "2026-10-26", to: "2026-12-06" });
    expect(gridRange("2026-02")).toEqual({ from: "2026-01-26", to: "2026-03-01" });
    expect(parseDay("2026-10-22")).toBe("2026-10-22");
    expect(parseDay("2026-02-30")).toBeNull();
    expect(parseDay("22-10-2026")).toBeNull();
  });
});

describe("My calendar (portal-ui-redesign, decision 8)", () => {
  it("asks /me/calendar for the month's grid and draws the three kinds in their tones", async () => {
    const api = browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10", day: "2026-10-22" }} />);
    const grid = await screen.findByRole("table", { name: "October 2026" });
    const call = api.calls.find((c) => c.path.startsWith("/me/calendar"))!;
    expect(call.path).toBe("/me/calendar?from=2026-09-28&to=2026-11-01");
    const day = within(grid).getByRole("button", { name: /^Thursday, 22 October:/ });
    // " (Today)" when the suite runs on 22 Oct 2026 itself
    expect(day).toHaveAccessibleName(/^Thursday, 22 October: 1 hearing, 1 action due, 1 next date to confirm( \(Today\))?$/);
    const kinds = Array.from(day.querySelectorAll("[data-kind]")).map((e) => e.getAttribute("data-kind"));
    // up to two events, then "+1 more"
    expect(kinds).toEqual(["hearing", "action_due"]);
    expect(within(day).getByText("+1 more")).toBeInTheDocument();
    expect(day.querySelector("[data-kind='hearing']")!.className).toMatch(/ev-hearing/);
    expect(day.querySelector("[data-kind='action_due']")!.className).toMatch(/ev-action_due/);
    // weekday headers and the outside days of the neighbouring months
    expect(within(grid).getAllByRole("columnheader")).toHaveLength(7);
    expect(within(grid).getByRole("button", { name: /^Monday, 28 September/ })).toBeInTheDocument();
  });

  it("the legend hides a kind on screen only; the API is not asked again", async () => {
    const api = browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10", day: "2026-10-22" }} />);
    const grid = await screen.findByRole("table", { name: "October 2026" });
    const legend = screen.getByRole("group", { name: "Show on the calendar" });
    const hearings = within(legend).getByRole("button", { name: "Hearings" });
    expect(hearings).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(hearings);
    expect(hearings).toHaveAttribute("aria-pressed", "false");
    const day = within(grid).getByRole("button", { name: /^Thursday, 22 October:/ });
    expect(day).toHaveAccessibleName(/^Thursday, 22 October: 1 action due, 1 next date to confirm( \(Today\))?$/);
    expect(day.querySelector("[data-kind='hearing']")).toBeNull();
    const agenda = screen.getByRole("region", { name: "Agenda" });
    expect(within(agenda).queryByText("Hearing")).toBeNull();
    expect(api.calls.filter((c) => c.path.startsWith("/me/calendar"))).toHaveLength(1);
  });

  it("marks today (IST) and opens on the current month's grid", async () => {
    const today = todayIst();
    const api = browserApi(routes(OFFICER, { "GET /me/calendar": { items: [] } }));
    renderWithClient(<MyCalendar params={{}} />);
    await screen.findByRole("table");
    const range = gridRange(monthOf(today));
    expect(api.calls.find((c) => c.path.startsWith("/me/calendar"))!.path).toBe(`/me/calendar?from=${range.from}&to=${range.to}`);
    const current = document.querySelector("td[aria-current='date']")!;
    expect(current).not.toBeNull();
    expect(within(current as HTMLElement).getByRole("button")).toHaveAccessibleName(/\(Today\)$/);
    expect(within(current as HTMLElement).getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("Previous, Next and Today change the query string", async () => {
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10", day: "2026-10-22" }} />);
    await screen.findByRole("table", { name: "October 2026" });
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?month=2026-09");
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?month=2026-11");
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar");
    // a day of the next month moves the month with it
    await userEvent.click(screen.getByRole("button", { name: /^Sunday, 1 November/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?month=2026-11&day=2026-11-01");
  });

  it("a day fills the agenda: Hearing / Due / Confirm badges in the fixed leading column, case links and details", async () => {
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10", day: "2026-10-22" }} />);
    await screen.findByRole("table", { name: "October 2026" });
    const agenda = screen.getByRole("region", { name: "Agenda" });
    expect(screen.getByRole("heading", { name: "Thursday, 22 October" })).toBeInTheDocument();
    const rows = within(agenda).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    for (const [row, badge] of [
      [rows[0]!, "Hearing"],
      [rows[1]!, "Due"],
      [rows[2]!, "Confirm"],
    ] as const) {
      const lead = row.firstElementChild as HTMLElement;
      expect(lead).toHaveAttribute("data-lead", "lead");
      expect(within(lead).getByText(badge)).toBeInTheDocument();
    }
    expect(within(rows[0]!).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-000001");
    expect(within(rows[0]!).getByText("Court 3 · item 14 · Admission")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(rows[2]!).getByRole("link", { name: "Open the review" })).toHaveAttribute("href", "/alerts/next-dates?q=c3");
  });

  it("a day with nothing says so", async () => {
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10", day: "2026-10-23" }} />);
    await screen.findByRole("table", { name: "October 2026" });
    expect(screen.getByText("Nothing on this day")).toBeInTheDocument();
  });

  it("the phone dots carry no text: every day's button has an accessible name", async () => {
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10" }} />);
    const grid = await screen.findByRole("table", { name: "October 2026" });
    for (const button of within(grid).getAllByRole("button")) expect(button).toHaveAccessibleName(/^\w+day, \d+ \w+: /);
    for (const ev of grid.querySelectorAll("[data-kind]")) expect(ev).toHaveAttribute("aria-hidden", "true");
    expect(within(grid).getByRole("button", { name: "Wednesday, 28 October: 1 hearing" })).toBeInTheDocument();
    expect(within(grid).getByRole("button", { name: "Friday, 23 October: nothing" })).toBeInTheDocument();
  });

  it("the page has at most one primary button (decision 16)", async () => {
    browserApi(routes());
    const { container } = renderWithClient(<MyCalendar params={{ month: "2026-10" }} />);
    await screen.findByRole("table", { name: "October 2026" });
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });
});

describe("the Department hearings view (portal-ui-redesign, decision 8; question 6)", () => {
  it("no switch for a department officer", async () => {
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ month: "2026-10" }} />);
    await screen.findByRole("table", { name: "October 2026" });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("radiogroup", { name: "Calendar view" })).toBeNull();
  });

  it("a whole-department member gets the switch, which shows /calendar unchanged", async () => {
    const api = browserApi(
      routes(OFFICER, {
        "GET /inbox/counts": { departments: [{ office_code: "EDU", whole_department: true }] },
        "GET /calendar": { items: [] },
      }),
    );
    const { unmount } = renderWithClient(<MyCalendar params={{ month: "2026-10" }} />);
    const sw = await screen.findByRole("radiogroup", { name: "Calendar view" });
    expect(within(sw).getByRole("radio", { name: "My dates" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(sw).getByRole("radio", { name: "Department hearings" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/calendar?view=department");
    unmount();
    renderWithClient(<MyCalendar params={{ view: "department" }} />);
    expect(await screen.findByRole("button", { name: "Next 7 days" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(api.calls.some((c) => c.path === "/calendar")).toBe(true));
    expect(screen.getByRole("radio", { name: "Department hearings" })).toHaveAttribute("aria-checked", "true");
  });

  it("a State-wide reader gets the switch without asking /inbox/counts; ?view=department is ignored for others", async () => {
    const api = browserApi(routes(["cases.view_all", "cases.view_scope"], { "GET /custody/recipients": { departments: [], items: [], units: [], total: 0 } }));
    const { unmount } = renderWithClient(<MyCalendar params={{ view: "department" }} />);
    expect(await screen.findByRole("radiogroup", { name: "Calendar view" })).toBeInTheDocument();
    expect(await screen.findByText("Choose a department to see its hearings.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/inbox/counts"))).toBe(false);
    unmount();
    browserApi(routes());
    renderWithClient(<MyCalendar params={{ view: "department", month: "2026-10" }} />);
    expect(await screen.findByRole("table", { name: "October 2026" })).toBeInTheDocument();
  });
});

describe("/alerts/calendar (portal-ui-redesign, decision 8)", () => {
  it("goes to the Department hearings view for a whole-department member, to My calendar otherwise", async () => {
    resetNav("/alerts/calendar");
    browserApi(routes(OFFICER, { "GET /inbox/counts": { departments: [{ office_code: "EDU", whole_department: true }] } }));
    const { unmount } = renderWithClient(<CalendarRedirect params={{ month: "2026-10" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/calendar?month=2026-10&view=department"));
    unmount();
    resetNav("/alerts/calendar");
    browserApi(routes());
    renderWithClient(<CalendarRedirect params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/calendar"));
  });
});

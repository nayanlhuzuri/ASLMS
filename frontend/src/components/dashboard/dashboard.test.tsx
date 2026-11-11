import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardDepartment, DashboardMe, DashboardState } from "@/lib/api/types";
import { nb } from "@/test/dates";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, labels, makeMe, renderWithClient } from "@/test/render";

import { Dashboard } from "./Dashboard";

const CASE = { id: "c1", ref_no: "EDU/2026/0001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" };

function department(code: string, name: string, extra: Partial<DashboardDepartment> = {}): DashboardDepartment {
  return {
    department: { code, name },
    generated_at: "2026-10-10T04:30:00Z",
    cases: { claimed_active: 128400, claimed_disposed: 12, not_allotted_active: 3, watching_active: 1, to_close: 0, closed: 0 },
    hearings: {
      total: 2,
      critical: 1,
      items: [
        { case: CASE, date: "2026-10-11", court_no: "3", item_no: "14", critical: true, approximate: false },
        { case: { ...CASE, id: "c2", case_no_text: "WA/55/2026" }, date: "2026-10-15", court_no: "5", item_no: "2", critical: false, approximate: false },
      ],
    },
    attention: { compliance_due_soon: 4, compliance_overdue: 1, next_dates_to_review: null, recent_order_next_dates: [], to_close: 0 },
    recommendations: { high: 5, medium: 7, transfers_in_open: 2 },
    pending_actions: { held: 9, overdue: 3, due_soon: 2, no_due_date: 1, items: null },
    custody_by_office: [{ office_code: "EDU-DSE", office_name: "Secondary Education", holder_department_code: "EDU", held: 4, with_pending_action: 2, overdue: 1 }],
    ...extra,
  };
}

const PERSONAL: DashboardMe = {
  generated_at: "2026-10-10T04:30:00Z",
  cases: [{ department_code: "EDU", department_name: "Education", allotted_active: 6, allotted_disposed: 2, counsel_active: null }],
  files: { held: 3, with_pending_action: 2, overdue: 1, items: [] },
  alerts: {
    unread: 2,
    open: { critical: 1, high: 0, normal: 1 },
    items: [
      { id: "a1", ref_no: "ALR-1", kind: "hearing", kind_label: "Hearing", severity: "critical", status: "open", title: "Hearing tomorrow: WP(C)/1234/2026", summary: "Hearing tomorrow", created_at: "2026-10-10T01:00:00Z", notified_at: "2026-10-10T01:00:00Z", due_at: null, case: CASE, case_visible: true },
    ],
  },
  hearings: { total: 0, critical: 0, items: [] },
  drafts: 1,
  headline: {
    to_claim: null,
    hearings_week: { total: 0, within_48h: 0 },
    files_with_me: { total: 3, due_today: 0 },
    overdue_actions: { total: 1, oldest_days: 2 },
    next_dates_to_confirm: null,
  },
  upcoming: [],
  attention: [],
};

const STATE: DashboardState = {
  generated_at: "2026-10-10T04:30:00Z",
  by_department: [
    { code: "EDU", name: "Education", is_active: true, claimed_active: 10, claimed_disposed: 1, recommended_high: 2, recommended_medium: 3, hearings_7d: 4, pending_actions: 5, overdue_actions: 1, compliance_due_soon: 2, compliance_overdue: 0 },
  ],
  not_claimed: { active: 40, recommended: 12, hearing_7d: 6 },
  hearings: { total: 0, critical: 0, items: [] },
  overdue_actions: { total: 1, by_holder: [{ code: "EDU", overdue: 1 }], by_owner: [{ code: "EDU", overdue: 1 }] },
  compliance: { due_soon: 2, overdue: 0 },
};

beforeEach(() => {
  resetNav("/");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Opens "More about my work", where the rest of the personal block is folded. */
async function openMore() {
  await userEvent.click(await screen.findByRole("button", { name: "More About My Work" }));
}

describe("dashboard", () => {
  it("shows only the blocks /dashboard names", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": PERSONAL,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My Work" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "State Overview" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/dashboard/state"))).toBe(false);
    expect(api.calls.some((c) => c.path.startsWith("/dashboard/department"))).toBe(false);
    await openMore();
    expect(await screen.findByText(/Hearing tomorrow/)).toBeInTheDocument();
  });

  it("offers a department selector when there are two departments", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }] },
      "GET /dashboard/department?department=EDU": department("EDU", "Education"),
      "GET /dashboard/department?department=HEALTH": department("HEALTH", "Health"),
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "Department: Education" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Department"), "HEALTH");
    expect(await screen.findByRole("region", { name: "Department: Health" })).toBeInTheDocument();
    expect(api.calls.map((c) => c.path)).toContain("/dashboard/department?department=HEALTH");
  });

  it("shows the tiles, the hearing band in the date cell and the Indian grouping", async () => {
    // 12:00 IST on 10 Oct 2026: the 11th is tomorrow, the 15th in 5 days (design next-hearing-highlight, decision 11)
    vi.useFakeTimers({ now: new Date("2026-10-10T06:30:00Z"), toFake: ["Date"] });
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByText("1,28,400")).toBeInTheDocument();
    expect(within(block).getByText("Recommendations Awaiting Review")).toBeInTheDocument();
    const rows = within(block).getAllByRole("row");
    const critical = rows.find((r) => within(r).queryByText("WP(C)/1234/2026"))!;
    expect(critical.querySelector('[data-band="tomorrow"]')).toHaveTextContent("Tomorrow · 11 Oct 2026");
    // case references are links to the case page (design portal-cases, decision 2)
    expect(within(critical).getByRole("link", { name: "WP(C)/1234/2026" })).toHaveAttribute(
      "href",
      "/cases/EDU-2026-0001",
    );
    const later = rows.find((r) => within(r).queryByText("WA/55/2026"))!;
    expect(later.querySelector('[data-band="week"]')).toHaveTextContent("In 5 Days · 15 Oct 2026");
    // the date cell carries the band, so the separate badge column is gone
    expect(within(block).queryByText("Within 48 Hours")).toBeNull();
    expect(within(block).queryByText("This Week")).toBeNull();
    const table = within(block).getAllByRole("table").find((t) => within(t).queryByText("WA/55/2026"))!;
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Date", "Case", "Court", "Item"]);
    expect(within(block).getByText("Secondary Education")).toBeInTheDocument();
  });

  it("does not render sections the API returns as null", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education", {
        recommendations: null,
        pending_actions: null,
        custody_by_office: null,
      }),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).queryByText("Recommendations Awaiting Review")).toBeNull();
    expect(within(block).queryByText("Pending Actions")).toBeNull();
    expect(within(block).queryByText("Cases by Office")).toBeNull();
    expect(within(block).queryByText("Open Transfers")).toBeNull();
    expect(within(block).queryByText("Next Dates to Enter")).toBeNull();
    expect(within(block).getByText("Hearings in 7 Days")).toBeInTheDocument();
  });

  it("one failing view shows its error while the others render", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"]),
      "GET /dashboard": { me: true, departments: [], state: true },
      "GET /dashboard/me": PERSONAL,
      "GET /dashboard/state": json(500, { detail: "boom" }),
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My Work" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "State" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/?view=state");
    renderWithClient(<Dashboard params={{ view: "state" }} />);
    const state = await screen.findByRole("region", { name: "State Overview" });
    await waitFor(() => expect(within(state).getByText("This block could not be loaded.")).toBeInTheDocument());
    expect(within(state).getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });

  it("the State block lists departments and the not-claimed row", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    const table = await screen.findByRole("table", { name: "Cases by Department" });
    expect(within(table).getByText("Education")).toBeInTheDocument();
    expect(within(table).getByRole("rowheader", { name: "Not Claimed" })).toBeInTheDocument();
  });

  it("the super admin sees the ticket panel first, with counts by kind and department", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state", "admin.tickets"], "super_admin"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
      "GET /reference/labels": { roles: [], office_kinds: [], ticket_kinds: [{ code: "head_change", label: "Head change" }] },
      "GET /admin/tickets/counts": {
        open: 3,
        open_by_kind: { head_change: 3 },
        open_by_department: { EDU: 2, HEALTH: 1 },
        oldest_open_at: "2026-10-09T05:00:00Z",
        departments_without_head: 1,
      },
    });
    renderWithClient(<Dashboard />);
    await screen.findByText("Open Tickets");
    const panel = screen.getByRole("region", { name: "Tickets Awaiting Action" });
    expect(within(panel).getByText("Departments Without a Head")).toBeInTheDocument();
    expect(await within(panel).findByRole("rowheader", { name: "Head Change" })).toBeInTheDocument();
    expect(within(panel).getByRole("rowheader", { name: "EDU" })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open the Tickets List" })).toHaveAttribute("href", "/admin/tickets");
    const regions = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
    expect(regions[0]).toBe("Tickets Awaiting Action");
  });

  it("no ticket panel without a ticket function", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": PERSONAL,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My Work" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Tickets Awaiting Action" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/admin/tickets"))).toBe(false);
  });

  it("a department admin who proposes head changes gets the panel, which says when nothing is open", async () => {
    browserApi({
      "GET /me": makeMe(["users.view", "users.propose_head"], "dept_admin"),
      "GET /admin/tickets/counts": { open: 0, open_by_kind: {}, open_by_department: {}, oldest_open_at: null },
    });
    renderWithClient(<Dashboard />);
    await screen.findByText("No open tickets.");
    const panel = screen.getByRole("region", { name: "Tickets Awaiting Action" });
    expect(within(panel).queryByText("Departments Without a Head")).toBeNull();
  });

  it("a login without case functions gets the short page", async () => {
    const api = browserApi({ "GET /me": makeMe(["users.view", "offices.manage"], "dept_admin") });
    renderWithClient(<Dashboard />);
    expect(await screen.findByText("There is no case dashboard for your login.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Administration" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/dashboard")).toBe(false);
  });

  it("links My Alerts to /alerts by View All and the Cases with me number to Working on, With me (case-inbox-merge, decision 13)", async () => {
    const hidden = { ...CASE, id: "c9", ref_no: "EDU/2026/0009", case_no_text: "WA/9/2026" };
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": {
        ...PERSONAL,
        alerts: {
          ...PERSONAL.alerts,
          items: [
            ...PERSONAL.alerts.items,
            { id: "a2", ref_no: "ALR-2", kind: "workflow", kind_label: "File movement", severity: "normal", status: "open", title: "File recalled: WA/9/2026", summary: "File recalled", created_at: "2026-10-10T02:00:00Z", notified_at: "2026-10-10T02:00:00Z", due_at: null, case: hidden, case_visible: false },
          ],
        },
      },
    });
    renderWithClient(<Dashboard />);
    await openMore();
    await screen.findByText(/File recalled/);
    const block = screen.getByRole("region", { name: "My Work" });
    expect(within(block).getByRole("link", { name: "View All My Alerts" })).toHaveAttribute("href", "/alerts");
    for (const link of within(block).getAllByRole("link", { name: "Cases with Me: 3" })) expect(link).toHaveAttribute("href", "/inbox/with-me");
    // a visible case is a link; a case the reader can no longer open is text
    expect(within(block).getByRole("link", { name: "WP(C)/1234/2026" })).toHaveAttribute("href", "/cases/EDU-2026-0001");
    expect(within(block).getByText("WA/9/2026").tagName).toBe("SPAN");
    expect(within(block).queryByRole("link", { name: "WA/9/2026" })).toBeNull();
    expect(document.getElementById("alerts")).not.toBeNull();
  });

  it("the State block links to Reports with reports.state only (portal-reports)", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state", "reports.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    const { unmount } = renderWithClient(<Dashboard />);
    await screen.findByRole("table", { name: "Cases by Department" });
    const block = screen.getByRole("region", { name: "State Overview" });
    expect(within(block).getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports/pending-cases");
    // design data-collection-redesign, decision 5: a link to the Overview for a data reader, no figure
    expect(within(block).getByRole("link", { name: "Data Collection Progress" })).toHaveAttribute("href", "/data/overview");
    unmount();
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    await screen.findByRole("table", { name: "Cases by Department" });
    const plain = screen.getByRole("region", { name: "State Overview" });
    expect(within(plain).queryByRole("link", { name: "Reports" })).toBeNull();
    expect(within(plain).queryByRole("link", { name: "Data Collection Progress" })).toBeNull();
  });

  it("a department block links to that department's reports with reports.department there", async () => {
    const routes = {
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education"),
    };
    const reader = makeMe(["cases.view_scope", "reports.department"]);
    reader.memberships = (reader.memberships ?? []).map((m) => ({ ...m, functions: ["cases.view_scope", "reports.department"] }));
    browserApi({ ...routes, "GET /me": reader });
    const { unmount } = renderWithClient(<Dashboard />);
    await screen.findByText("1,28,400");
    const block = screen.getByRole("region", { name: "Department: Education" });
    expect(within(block).getByRole("link", { name: "Department Reports" })).toHaveAttribute(
      "href",
      "/reports/pending-cases?department=EDU",
    );
    // design case-inbox-simplify, decision 16: the department's pending figure leads to that department's Department tab
    expect(within(block).getByRole("link", { name: "Pending Actions: 9" })).toHaveAttribute("href", "/inbox/department?department=EDU");
    unmount();
    browserApi({ ...routes, "GET /me": makeMe(["cases.view_scope"]) });
    renderWithClient(<Dashboard />);
    await screen.findByText("1,28,400");
    const plain = screen.getByRole("region", { name: "Department: Education" });
    expect(within(plain).queryByRole("link", { name: "Department Reports" })).toBeNull();
  });

  it("Next Dates That Differ From the Court links to Department Cases with the filter (next-date-direct, decision 5)", async () => {
    const d = department("EDU", "Education", {
      attention: { compliance_due_soon: 0, compliance_overdue: 0, next_dates_to_review: null, recent_order_next_dates: [], next_dates_differ: 2, to_close: 0 },
    });
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": d,
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByRole("link", { name: "Next Dates That Differ From the Court" })).toHaveAttribute(
      "href",
      "/inbox/department?department=EDU&next_differs=true",
    );
  });

  it("Next dates to enter links to the review list for the department when above zero (portal-next-dates, decision 13)", async () => {
    const att = (n: number | null, recent: DashboardDepartment["attention"]["recent_order_next_dates"] = []) =>
      department("EDU", "Education", {
        attention: { compliance_due_soon: 0, compliance_overdue: 0, next_dates_to_review: n, recent_order_next_dates: recent, to_close: 0 },
      });
    const routes = (d: DashboardDepartment) => ({
      "GET /me": makeMe(["cases.view_scope", "next_dates.review"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": d,
    });
    browserApi(
      routes(
        att(3, [
          { case: CASE, next_date: "2026-10-26", source: "order_period", review_status: "pending" },
          { case: { ...CASE, id: "c2", case_no_text: "WA/55/2026" }, next_date: "2026-11-20", source: "order_specific", review_status: "not_needed" },
        ]),
      ),
    );
    const { unmount } = renderWithClient(<Dashboard />);
    let block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByRole("link", { name: "Next Dates to Enter" })).toHaveAttribute("href", "/alerts/next-dates?owner=EDU");
    const table = within(block).getByRole("table", { name: "Recent Order Next Dates" });
    expect(within(table).getByRole("columnheader", { name: "Where It Came From" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(within(table).getByText("Counted From the Order")).toBeInTheDocument();
    expect(within(table).getByText("Date in the Order")).toBeInTheDocument();
    // design next-date-direct: an old pending reading is shown directly, so both rows read In Use
    expect(within(table).getAllByText("In Use")).toHaveLength(2);
    unmount();
    browserApi(routes(att(0)));
    const second = renderWithClient(<Dashboard />);
    block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByText("Next Dates to Enter")).toBeInTheDocument();
    expect(within(block).queryByRole("link", { name: "Next Dates to Enter" })).toBeNull();
    second.unmount();
    browserApi(routes(att(null)));
    renderWithClient(<Dashboard />);
    block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).queryByText("Next Dates to Enter")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------- round 4 (decision 23, A7)

const HEADLINE: DashboardMe["headline"] = {
  to_claim: { high: 5, medium: 7 },
  hearings_week: { total: 4, within_48h: 2 },
  files_with_me: { total: 6, due_today: 1 },
  overdue_actions: { total: 3, oldest_days: 6 },
  next_dates_to_confirm: 2,
};

const ATTENTION: DashboardMe["attention"] = [
  { kind: "overdue_action", case: CASE, title: "Parawise comments", date: "2026-10-15", detail: "Overdue 6 days", pending_action: "parawise_comments", overdue_days: 6, next_date_id: null },
  { kind: "confirm_next_date", case: { ...CASE, id: "c3", case_no_text: "WA/3/2026" }, title: "Next Date to Confirm", date: "2026-11-19", detail: "Suggested from an order", pending_action: null, overdue_days: 0, next_date_id: "nd-1" },
  { kind: "due_soon", case: { ...CASE, id: "c4", case_no_text: "WA/4/2026" }, title: "Reply", date: "2026-10-22", detail: "Due tomorrow", pending_action: "reply", overdue_days: 0, next_date_id: null },
  { kind: "file_received", case: { ...CASE, id: "c5", case_no_text: "WA/5/2026" }, title: "Examine", date: "2026-10-21", detail: "From Edu Admin, Joint Secretary", pending_action: "examine", overdue_days: 0, next_date_id: null },
];

function personal(extra: Partial<DashboardMe> = {}): DashboardMe {
  return { ...PERSONAL, headline: HEADLINE, attention: ATTENTION, ...extra };
}

const CLAIMER = makeMe(["cases.view_scope", "cases.claim", "next_dates.review"], "dept_admin");

function mine(data: DashboardMe = personal()) {
  return { "GET /me": CLAIMER, "GET /dashboard": { me: true, departments: [], state: false }, "GET /dashboard/me": data };
}

describe("the personal dashboard (portal-ui-redesign, decision 23)", () => {
  it("greets by the IST hour with the primary office and the IST date", async () => {
    vi.useFakeTimers({ now: new Date("2026-10-21T03:00:00Z"), toFake: ["Date"] }); // 08:30 IST
    browserApi(mine());
    const { unmount } = renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good Morning, Anita" })).toBeInTheDocument();
    expect(screen.getByText("Under Secretary · Education")).toBeInTheDocument();
    expect(screen.getByText("Wednesday, 21 October 2026")).toBeInTheDocument();
    unmount();
    vi.setSystemTime(new Date("2026-10-21T09:00:00Z")); // 14:30 IST
    browserApi(mine());
    const second = renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good Afternoon, Anita" })).toBeInTheDocument();
    second.unmount();
    vi.setSystemTime(new Date("2026-10-21T13:00:00Z")); // 18:30 IST
    browserApi(mine());
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good Evening, Anita" })).toBeInTheDocument();
  });

  it("five headline numbers, each a link to its list; a null figure is left out", async () => {
    browserApi(mine());
    const { unmount } = renderWithClient(<Dashboard />);
    const headline = await screen.findByRole("region", { name: "Headline Numbers" });
    const links = within(headline).getAllByRole("link");
    expect(links.map((l) => [l.getAttribute("aria-label"), l.getAttribute("href")])).toEqual([
      ["Cases to Claim: 12", "/claim/recommended"],
      ["Hearings This Week: 4", "/calendar"],
      ["Cases with Me: 6", "/inbox/with-me"],
      ["Overdue Actions: 3", "/inbox/with-me?overdue=true"],
      ["Next Dates to Enter: 2", "/alerts/next-dates"],
    ]);
    expect(within(headline).getByText("5 strong · 7 possible")).toBeInTheDocument();
    expect(within(headline).getByText("2 within 48 hours")).toBeInTheDocument();
    expect(within(headline).getByText("1 due today")).toBeInTheDocument();
    expect(within(headline).getByText("Oldest 6 days")).toBeInTheDocument();
    unmount();
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": personal({ headline: { ...HEADLINE, to_claim: null, next_dates_to_confirm: null } }),
    });
    renderWithClient(<Dashboard />);
    const fewer = await screen.findByRole("region", { name: "Headline Numbers" });
    expect(within(fewer).getAllByRole("link")).toHaveLength(3);
    expect(fewer).toHaveAttribute("data-count", "3");
    expect(within(fewer).queryByText("Cases to Claim")).toBeNull();
    expect(within(fewer).queryByText("Next Dates to Enter")).toBeNull();
  });

  it("under reduced motion the numbers show their final value at once", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
    browserApi(mine());
    renderWithClient(<Dashboard />);
    const headline = await screen.findByRole("region", { name: "Headline Numbers" });
    expect(within(headline).getByText("12")).toBeInTheDocument();
    expect(within(headline).getByText("6")).toBeInTheDocument();
  });

  it("Review cases to claim is the one primary, only with cases to claim and Case claim shown", async () => {
    browserApi(mine());
    const { container, unmount } = renderWithClient(<Dashboard />);
    expect(await screen.findByRole("link", { name: "Review Cases to Claim" })).toHaveAttribute("href", "/claim/recommended");
    expect(container.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
    unmount();
    browserApi(mine(personal({ headline: { ...HEADLINE, to_claim: { high: 0, medium: 0 } } })));
    const none = renderWithClient(<Dashboard />);
    await screen.findByRole("region", { name: "Headline Numbers" });
    expect(screen.queryByRole("link", { name: "Review Cases to Claim" })).toBeNull();
    expect(none.container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("Needs your attention leads every row with a Lead badge and links to the case or the review", async () => {
    browserApi(mine());
    renderWithClient(<Dashboard />);
    const list = await screen.findByRole("list", { name: "Needs Your Attention" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    for (const row of rows) expect(row.firstElementChild).toHaveAttribute("data-lead", "lead");
    expect(rows.map((r) => r.firstElementChild!.textContent)).toEqual(["Overdue", "Next Date to Enter", "Due Soon", "Case Received"]);
    expect(within(rows[0]!).getByRole("link", { name: "Parawise Comments" })).toHaveAttribute("href", "/cases/EDU-2026-0001");
    expect(within(rows[0]!).getByText("WP(C)/1234/2026 · Overdue 6 days")).toBeInTheDocument();
    expect(within(rows[1]!).getByRole("link", { name: "Next Date to Confirm" })).toHaveAttribute("href", "/alerts/next-dates?q=c3");
  });

  it("Upcoming hearings lead with the date chip, red today and tomorrow, and the band's words", async () => {
    vi.useFakeTimers({ now: new Date("2026-10-21T03:00:00Z"), toFake: ["Date"] });
    browserApi(
      mine(
        personal({
          upcoming: [
            { case: CASE, date: "2026-10-22", court_no: "3", item_no: "14", critical: false, approximate: false, this_week: true },
            // the API's 48-hour flag no longer colours the row: the band of the IST day does (next-hearing-highlight)
            { case: { ...CASE, id: "c2", case_no_text: "WA/55/2026" }, date: "2026-10-23", court_no: null, item_no: null, critical: true, approximate: false, this_week: true },
            { case: { ...CASE, id: "c3", case_no_text: "WA/56/2026" }, date: "2026-10-28", court_no: null, item_no: null, critical: false, approximate: false, this_week: false },
          ],
        }),
      ),
    );
    renderWithClient(<Dashboard />);
    const list = await screen.findByRole("list", { name: "Upcoming Hearings" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.firstElementChild!.getAttribute("data-lead"))).toEqual(["date", "date", "date"]);
    expect(rows[0]!.firstElementChild!.className).toMatch(/hot/);
    expect(rows[1]!.firstElementChild!.className).not.toMatch(/hot/);
    expect(rows[2]!.firstElementChild!.className).not.toMatch(/hot/);
    // the trail is the word alone: the date chip already shows the date
    const bands = rows.map((r) => r.querySelector("[data-band]")!);
    expect(bands.map((b) => b.getAttribute("data-band"))).toEqual(["tomorrow", "week", "week"]);
    expect(bands.map((b) => b.textContent)).toEqual(["Tomorrow", "In 2 Days", "In 7 Days"]);
    for (const b of bands) expect(b.querySelector("time")).toBeNull();
    // design portal-screen-fixes-work, decisions 22 and 23: "Item" with a capital; on phones the badge goes under the
    // case number
    expect(within(rows[0]!).getByText("Court 3 · Item 14")).toBeInTheDocument();
    for (const r of rows) expect(r).toHaveAttribute("data-stack-trail");
    // design portal-ui-kit-fixes, decision 22: "View All", the target named for screen readers
    expect(screen.getByRole("link", { name: "View All Upcoming Hearings" })).toHaveAttribute("href", "/calendar");
  });

  it("the view switch shows only with more than one view", async () => {
    browserApi(mine());
    const { unmount } = renderWithClient(<Dashboard />);
    await screen.findByRole("region", { name: "Headline Numbers" });
    expect(screen.queryByRole("radiogroup", { name: "Dashboard View" })).toBeNull();
    unmount();
    browserApi({
      ...mine(),
      "GET /dashboard": { me: true, departments: [{ code: "EDU", name: "Education" }], state: false },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const group = await screen.findByRole("radiogroup", { name: "Dashboard View" });
    expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["My Work", "Department"]);
    await userEvent.click(within(group).getByRole("radio", { name: "Department" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/?view=department");
  });

  it("switching My Work to Department slides the same thumb to a new place (design portal-motion, decision 11)", async () => {
    const boxes: Record<string, { left: number; width: number }> = { "My Work": { left: 2, width: 80 }, Department: { left: 84, width: 104 } };
    const left = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
      return this.getAttribute("role") === "radio" ? (boxes[this.textContent ?? ""]?.left ?? 0) : 0;
    });
    const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) {
      return this.getAttribute("role") === "radio" ? (boxes[this.textContent ?? ""]?.width ?? 0) : 0;
    });
    try {
      browserApi({
        ...mine(),
        "GET /dashboard": { me: true, departments: [{ code: "EDU", name: "Education" }], state: false },
        "GET /dashboard/department": department("EDU", "Education"),
      });
      const view = renderWithClient(<Dashboard />);
      const group = await screen.findByRole("radiogroup", { name: "Dashboard View" });
      const thumb = within(group).getByTestId("segment-thumb");
      expect(thumb).toHaveStyle({ left: "2px", width: "80px" });
      await userEvent.click(within(group).getByRole("radio", { name: "Department" }));
      expect(nav.replace).toHaveBeenLastCalledWith("/?view=department");
      // the address changes only `view`; the page renders again with it and the switch stays mounted
      view.rerender(<Dashboard params={{ view: "department" }} />);
      const after = within(screen.getByRole("radiogroup", { name: "Dashboard View" })).getByTestId("segment-thumb");
      expect(after).toBe(thumb);
      expect(after).toHaveStyle({ left: "84px", width: "104px" });
    } finally {
      left.mockRestore();
      width.mockRestore();
    }
  });

  it("the Department view keeps the department figures as headline numbers", async () => {
    browserApi({
      ...mine(),
      "GET /dashboard": { me: true, departments: [{ code: "EDU", name: "Education" }], state: false },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard params={{ view: "department" }} />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByText("1,28,400")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "My Work" })).toBeNull();
  });

  it("a State-wide reader without personal work opens on State", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: true, departments: [], state: true },
      "GET /dashboard/me": {
        ...PERSONAL,
        cases: [],
        headline: { ...PERSONAL.headline, files_with_me: { total: 0, due_today: 0 }, overdue_actions: { total: 0, oldest_days: null } },
      },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("table", { name: "Cases by Department" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "State" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("region", { name: "My Work" })).toBeNull();
  });
});

describe("every Upcoming hearings row has a badge (design portal-ui-polish, decision 14; next-hearing-highlight)", () => {
  it("each row's word and the chip's red follow the IST band, not the API's flags", async () => {
    // Saturday 24 Oct 2026, 11:30 IST
    vi.useFakeTimers({ now: new Date("2026-10-24T06:00:00Z"), toFake: ["Date"] });
    const row = (id: string, date: string, critical: boolean) => ({
      case: { ...CASE, id, case_no_text: `WA/${id}/2026` },
      date,
      court_no: null,
      item_no: null,
      critical,
      this_week: true,
      approximate: false,
    });
    browserApi(mine(personal({ upcoming: [row("1", "2026-10-24", true), row("2", "2026-10-25", false), row("3", "2026-10-26", true), row("4", "2026-10-30", false)] })));
    renderWithClient(<Dashboard />);
    const list = await screen.findByRole("list", { name: "Upcoming Hearings" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("[data-band]")!.textContent)).toEqual(["Today", "Tomorrow", "In 2 Days", "In 6 Days"]);
    expect(rows.map((r) => /hot/.test(r.firstElementChild!.className))).toEqual([true, true, false, false]);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("Blocks renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    const { unmount } = renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    const tables = within(block).getAllByRole("table");
    expect(tables.length).toBeGreaterThanOrEqual(2);
    for (const table of tables) expectDataTable(table);
    unmount();
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    await screen.findByRole("table", { name: "Cases by Department" });
    for (const table of screen.getAllByRole("table")) expectDataTable(table);
  });
});

describe("the greeting and the view switch (design portal-ui-polish-2, decisions 44 and 45)", () => {
  const STATE_ONLY = { me: true, departments: [], state: true };
  const NO_WORK = {
    ...PERSONAL,
    cases: [],
    upcoming: [],
    attention: [],
    headline: {
      ...PERSONAL.headline,
      to_claim: null,
      next_dates_to_confirm: null,
      hearings_week: { total: 0, within_48h: 0 },
      files_with_me: { total: 0, due_today: 0 },
      overdue_actions: { total: 0, oldest_days: null },
    },
  };

  it("greets a person by first name, with the designation and office under it and the IST date by the switch", async () => {
    vi.useFakeTimers({ now: new Date("2026-10-25T09:00:00Z"), toFake: ["Date"] }); // 14:30 IST, Sunday
    browserApi(mine());
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good Afternoon, Anita" })).toBeInTheDocument();
    expect(screen.getByText("Under Secretary · Education")).toBeInTheDocument();
    expect(screen.getByText("Sunday, 25 October 2026")).toBeInTheDocument();
  });

  it.each([
    ["the designation", "under secretary "],
    ["a user-type label", "Dept admin"],
    ["Super Administrator", "Super Administrator"],
    ["nothing", "   "],
  ])("an account whose full name is %s has no name in the greeting", async (_what, fullName) => {
    vi.useFakeTimers({ now: new Date("2026-10-25T09:00:00Z"), toFake: ["Date"] });
    const me = makeMe(["cases.view_scope", "cases.claim"], "dept_admin");
    me.user.full_name = fullName;
    browserApi({ ...mine(), "GET /me": me, "GET /reference/labels": labels() });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good Afternoon" })).toBeInTheDocument();
    expect(screen.getByText("Under Secretary · Education")).toBeInTheDocument();
  });

  it("each view has a tooltip and the chosen one's sentence is the line under the switch", async () => {
    browserApi({
      ...mine(),
      "GET /dashboard": { me: true, departments: [{ code: "EDU", name: "Education" }], state: false },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const group = await screen.findByRole("radiogroup", { name: "Dashboard View" });
    expect(within(group).getByRole("radio", { name: "My Work" })).toHaveAttribute("title", "My Work: your own cases.");
    expect(within(group).getByRole("radio", { name: "Department" })).toHaveAttribute("title", "Department: your department's cases.");
    expect(group).toHaveAccessibleDescription("My Work: your own cases.");
  });

  it("a login with the State view and no department sees Department disabled with its reason", async () => {
    const root = makeMe(["cases.view_all", "dashboard.state"], "super_admin", {
      memberships: [
        {
          id: "m-0",
          office: { code: "GOA", name: "Government of Assam", kind: "state" },
          department_code: null,
          designation: "Super Administrator",
          role: "super_admin",
          is_primary: true,
          is_active: true,
        },
      ],
    });
    root.user.full_name = "Super Administrator";
    browserApi({
      "GET /me": root,
      "GET /reference/labels": labels(),
      "GET /dashboard": STATE_ONLY,
      "GET /dashboard/me": PERSONAL,
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard params={{ view: "state" }} />);
    const group = await screen.findByRole("radiogroup", { name: "Dashboard View" });
    expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["My Work", "Department", "State"]);
    const dept = within(group).getByRole("radio", { name: "Department" });
    expect(dept).toHaveAttribute("aria-disabled", "true");
    expect(dept).toHaveAttribute("title", "Department: not available, because you are not in a department");
    await userEvent.click(dept);
    expect(nav.replace).not.toHaveBeenCalled();
    expect(screen.getByText("Super Administrator · Government of Assam")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: /^Good (Morning|Afternoon|Evening)$/ })).toBeInTheDocument();
    expect(group).toHaveAccessibleDescription("State: every case in the whole State.");
  });

  it("opens on State with the reason when there is no personal work", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": STATE_ONLY,
      "GET /dashboard/me": NO_WORK,
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByText("Opened on State because you have no cases of your own.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "State" })).toHaveAttribute("aria-checked", "true");
  });
});

describe("Ready to Close on the dashboards (design close-case, decisions 21 and 22)", () => {
  it("the personal attention list shows the ready_to_close item linking to the case", async () => {
    const ready: DashboardMe["attention"][number] = {
      kind: "ready_to_close",
      case: { ...CASE, id: "c9", case_no_text: "WA/9/2026", ref_no: "ASLMS/GHC/CASE/2026/000009" },
      title: "Ready to Close",
      date: "2026-10-20",
      detail: "Disposed by the court on 20 Oct 2026",
      pending_action: "examine",
      overdue_days: 0,
      next_date_id: null,
    };
    browserApi(mine(personal({ attention: [ready] })));
    renderWithClient(<Dashboard />);
    const panel = await screen.findByRole("list", { name: "Needs Your Attention" });
    expect(within(panel).getAllByText("Ready to Close").length).toBe(2); // the lead badge and the title
    expect(within(panel).getByRole("link", { name: "Ready to Close" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000009");
    expect(within(panel).getByText(/Disposed by the court on 20 Oct 2026/)).toBeInTheDocument();
  });

  it("the department Attention card's Ready to Close links to Department Cases with the disposed filter when above zero", async () => {
    const d = department("EDU", "Education", {
      attention: { compliance_due_soon: 0, compliance_overdue: 0, next_dates_to_review: null, recent_order_next_dates: [], to_close: 3 },
    });
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": d,
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByRole("link", { name: "Ready to Close" })).toHaveAttribute(
      "href",
      "/inbox/department?department=EDU&case_status=disposed",
    );
    expect(within(block).getByRole("link", { name: "Ready to Close" }).closest("li")).toHaveTextContent("Ready to Close3");
  });
});

describe("empty sections (design portal-ui-kit-fixes, decision 19)", () => {
  it("the department view's Pending Actions card shows when the server sends the list, empty or not", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education", {
        pending_actions: { held: 0, overdue: 0, due_soon: 0, no_due_date: 0, items: [] },
      }),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    const card = within(block).getByRole("heading", { name: "Pending Actions" }).closest("section")!;
    const empty = within(card).getByText("No Pending Actions.").closest("[data-compact]");
    expect(empty).not.toBeNull();
  });

  it("an empty overdue list with actions pending says none are overdue, never none pending", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education", {
        pending_actions: { held: 40, overdue: 0, due_soon: 2, no_due_date: 1, items: [] },
      }),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    const card = within(block).getByRole("heading", { name: "Pending Actions" }).closest("section")!;
    expect(within(card).getByText("No Overdue Pending Actions.")).toBeInTheDocument();
    expect(within(block).queryByText("No Pending Actions.")).toBeNull();
  });

  it("the card stays hidden when the server sends no list (reports function without tracking)", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).queryByRole("heading", { name: "Pending Actions" })).toBeNull();
    expect(within(block).queryByText("No Pending Actions.")).toBeNull();
    expect(within(block).queryByText("No Overdue Pending Actions.")).toBeNull();
  });

  it("More About My Work still hides Cases with Me when the reader holds none", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": PERSONAL,
    });
    renderWithClient(<Dashboard />);
    await openMore();
    expect(await screen.findByText(/Hearing tomorrow/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Cases with Me" })).toBeNull();
  });
});

describe("More About My Work (design dashboard-my-work-polish)", () => {
  const caseNo = (i: number) => `WP(C)/${100 + i}/2026`;
  const caseOf = (i: number) => ({ ...CASE, id: `c${100 + i}`, ref_no: `EDU/2026/0${100 + i}`, case_no_text: caseNo(i) });
  type Alert = DashboardMe["alerts"]["items"][number];
  const alert = (i: number, extra: Partial<Alert>): Alert => ({
    id: `a${i}`,
    ref_no: `ALR-${i}`,
    kind: "new_order",
    kind_label: "New order",
    severity: "normal",
    status: "open",
    title: `Something: ${caseNo(i)}`,
    summary: "Something",
    due_at: "2026-12-31T05:00:00Z",
    created_at: "2026-11-01T04:30:00Z",
    notified_at: `2026-11-${String(10 - i).padStart(2, "0")}T04:30:00Z`,
    case: caseOf(i),
    case_visible: true,
    hearing_date: null,
    band: null,
    ...extra,
  });
  const ALERTS: Alert[] = [
    alert(1, { kind: "hearing_due", kind_label: "Hearing due", severity: "critical", title: `Hearing on 11 Nov 2026: ${caseNo(1)}`, summary: "Hearing on 11 Nov 2026", hearing_date: "2026-11-11" }),
    alert(2, { kind: "hearing_due", kind_label: "Hearing due", severity: "high", title: `Hearing on 11 Nov 2026: ${caseNo(2)}`, summary: "Hearing on 11 Nov 2026", hearing_date: "2026-11-11" }),
    alert(3, { kind: "listed_tomorrow", kind_label: "Listed for tomorrow", severity: "high", title: `Hearing on 14 Nov 2026: ${caseNo(3)}`, summary: "Hearing on 14 Nov 2026", hearing_date: "2026-11-14" }),
    alert(4, { kind: "recommendation", kind_label: "Recommendation", severity: "high", title: `Strong match for EDU: ${caseNo(4)}`, summary: "Strong match for EDU", band: "high" }),
    alert(5, { kind: "recommendation", kind_label: "Recommendation", severity: "normal", title: `Suggested for EDU: ${caseNo(5)}`, summary: "Suggested for EDU", band: "medium" }),
    alert(6, { kind: "compliance_due", kind_label: "Compliance due", severity: "high", title: `Compliance due 20 Nov 2026: ${caseNo(6)}`, summary: "Compliance due 20 Nov 2026" }),
    alert(7, { kind: "admin_ticket", kind_label: "Admin ticket", title: "Admin ticket T-1 awaits your decision: Head change, EDU", summary: "Admin ticket T-1 awaits your decision: Head change, EDU", case: null, case_visible: false }),
  ];
  type File = DashboardMe["files"]["items"][number];
  const file = (i: number, extra: Partial<File>): File => ({
    case: caseOf(10 + i),
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    since: `2026-11-0${i}T04:30:00Z`,
    due_date: null,
    overdue_days: 0,
    holder_office_code: "EDU",
    ...extra,
  });
  const MINE: DashboardMe = {
    ...PERSONAL,
    cases: [
      { department_code: "EDU", department_name: "Education", allotted_active: 6, allotted_disposed: 2, counsel_active: null },
      { department_code: "HEALTH", department_name: "Health and Family Welfare", allotted_active: 1, allotted_disposed: 0, counsel_active: null },
    ],
    files: {
      held: 3,
      with_pending_action: 3,
      overdue: 1,
      items: [
        file(1, { due_date: "2026-11-07", overdue_days: 3 }),
        file(2, { due_date: "2026-11-15", pending_action: "reply", pending_action_label: "Reply" }),
        file(3, { due_date: null }),
      ],
    },
    alerts: { ...PERSONAL.alerts, items: ALERTS },
  };

  async function openMine(data: DashboardMe = MINE) {
    // 12:00 IST on Tuesday 10 Nov 2026
    vi.useFakeTimers({ now: new Date("2026-11-10T06:30:00Z"), toFake: ["Date"] });
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": data,
    });
    renderWithClient(<Dashboard />);
    await openMore();
    await screen.findByRole("table", { name: "My Alerts" });
    return screen.getByRole("region", { name: "My Work" });
  }

  const card = (block: HTMLElement, name: string) => within(block).getByRole("heading", { name, level: 3 }).closest("section")!;

  it("shows three cards with View All in their heads, and tables named by their hidden captions", async () => {
    const block = await openMine();
    const links: [string, string, string][] = [
      ["My Cases", "View All My Cases", "/inbox/my-cases"],
      ["Cases with Me", "View All Cases with Me", "/inbox/with-me"],
      ["My Alerts", "View All My Alerts", "/alerts"],
    ];
    for (const [title, name, href] of links) {
      const section = card(block, title);
      expect(within(section).getByRole("link", { name })).toHaveAttribute("href", href);
      const table = expectDataTable(within(section).getByRole("table", { name: title }));
      expect(table.querySelector("caption")!.className).toMatch(/srCaption/);
    }
    // the three names differ, and the cards come in today's order
    const headings = within(block)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent)
      .filter((t) => ["My Cases", "Cases with Me", "My Alerts"].includes(t ?? ""));
    expect(headings).toEqual(["My Cases", "Cases with Me", "My Alerts"]);
    expect(document.getElementById("alerts")?.querySelector("h3")).toHaveTextContent("My Alerts");
  });

  it("My Cases names the department, with right-aligned figures", async () => {
    const section = card(await openMine(), "My Cases");
    expect(within(section).getByText("Education")).toHaveAttribute("title", "EDU");
    expect(within(section).queryByText("EDU")).toBeNull();
    expect(section.querySelector(".mono")).toBeNull();
    const table = within(section).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Department", "Assigned, Active", "Disposed"]);
  });

  it("Cases with Me has one Due column with an overdue badge, a date and No Due Date, and the action's label", async () => {
    const section = card(await openMine(), "Cases with Me");
    const table = within(section).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Case", "Pending Action", "Due"]);
    const rows = within(table).getAllByRole("row").slice(1);
    const overdue = within(rows[0]!).getByText("Overdue by 3 Days");
    expect(overdue.closest("[class*=badge-danger]")).not.toBeNull();
    expect(overdue.closest("[title]")).toHaveAttribute("title", nb("7 Nov 2026"));
    expect(rows[1]).toHaveTextContent("15 Nov 2026");
    expect(within(rows[2]!).getByText("No Due Date")).toHaveClass("muted");
    expect(within(rows[0]!).getByText("Parawise Comments")).toBeInTheDocument();
    expect(within(table).queryByText("parawise_comments")).toBeNull();
    expect(within(table).queryByText("Overdue")).toBeNull();
  });

  it("says Overdue by 1 Day for one day", async () => {
    const section = card(
      await openMine({ ...MINE, files: { ...MINE.files, items: [file(1, { due_date: "2026-11-09", overdue_days: 1 })] } }),
      "Cases with Me",
    );
    expect(within(section).getByText("Overdue by 1 Day")).toBeInTheDocument();
  });

  it("My Alerts is a table of Type, Case, What Happened and Raised, the case number once, in the API's order", async () => {
    const section = card(await openMine(), "My Alerts");
    const table = within(section).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Type", "Case", "What Happened", "Raised"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[2]!.textContent)).toEqual(ALERTS.map((a) => a.summary));
    rows.forEach((row, i) => {
      const number = ALERTS[i]!.case?.case_no_text;
      if (number) expect(row.textContent!.split(number).length - 1).toBe(1);
    });
    // Raised is the latest notice's date, never the due time
    const raised = within(rows[0]!).getAllByRole("cell")[3]!;
    expect(raised.querySelector("time")).toHaveAttribute("dateTime", ALERTS[0]!.notified_at);
    expect(raised).toHaveTextContent("9 Nov 2026");
    expect(table).not.toHaveTextContent("31 Dec 2026");
    // a ticket has no case
    expect(within(rows[6]!).getAllByRole("cell")[1]).toHaveTextContent(/^—$/);
  });

  it("colours a hearing by its band, the same for critical and high, with Hearing first", async () => {
    const section = card(await openMine(), "My Alerts");
    const rows = within(within(section).getByRole("table")).getAllByRole("row").slice(1);
    const tomorrow = rows[0]!.querySelector("[data-band]")!;
    expect(tomorrow).toHaveAttribute("data-band", "tomorrow");
    expect(tomorrow).toHaveTextContent(/^Hearing · Tomorrow$/);
    const high = rows[1]!.querySelector("[data-band]")!;
    expect(high.className).toBe(tomorrow.className);
    expect(high.textContent).toBe(tomorrow.textContent);
    const week = rows[2]!.querySelector("[data-band]")!;
    expect(week).toHaveAttribute("data-band", "week");
    expect(week).toHaveTextContent(/^Hearing · In 4 Days$/);
  });

  it("shows a strong recommendation solid and a possible one outlined, both blue whatever the severity", async () => {
    const section = card(await openMine(), "My Alerts");
    const strong = within(section).getByTitle("Strong Match");
    const possible = within(section).getByTitle("Possible Match");
    expect(strong).toHaveAttribute("data-look", "solid");
    expect(possible).toHaveAttribute("data-look", "outline");
    for (const el of [strong, possible]) {
      expect(el.className).toMatch(/badge-info/);
      expect(el).toHaveTextContent("Recommendation");
    }
    expect(strong.querySelector(".visually-hidden")).toHaveTextContent("Strong Match");
    expect(possible.querySelector(".visually-hidden")).toHaveTextContent("Possible Match");
  });

  it("gives every other kind a neutral badge in Title Case, whatever its severity", async () => {
    const section = card(await openMine(), "My Alerts");
    const badge = within(section).getByTitle("Compliance Due");
    expect(badge).toHaveTextContent(/^Compliance Due$/);
    expect(badge.className).not.toMatch(/badge-(danger|warning|info|success)/);
    expect(within(section).getByTitle("Admin Ticket")).toBeInTheDocument();
    expect(within(section).queryByText("Hearing due")).toBeNull();
  });

  it("keeps My Alerts as a card with its empty state when there are none", async () => {
    vi.useFakeTimers({ now: new Date("2026-11-10T06:30:00Z"), toFake: ["Date"] });
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": { ...MINE, alerts: { ...MINE.alerts, items: [] } },
    });
    renderWithClient(<Dashboard />);
    await openMore();
    const section = card(await screen.findByRole("region", { name: "My Work" }), "My Alerts");
    expect(await within(section).findByText("No open alerts.")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "View All My Alerts" })).toHaveAttribute("href", "/alerts");
  });

  it("the department view's Pending Actions card keeps its Overdue column and shows the action's label", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education", {
        pending_actions: { held: 1, overdue: 1, due_soon: 0, no_due_date: 0, items: [file(1, { due_date: "2026-11-07", overdue_days: 3 })] },
      }),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    const table = await within(block).findByRole("table", { name: "Pending Actions" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Case", "Pending Action", "Due", "Overdue"]);
    expect(within(table).getByText("Parawise Comments")).toBeInTheDocument();
    expect(within(table).queryByText("parawise_comments")).toBeNull();
  });
});

describe("the one orange headline tile (design portal-navy-cream, decision 10)", () => {
  const tiles = () => screen.getAllByRole("link").filter((a) => /kpi/.test(a.className));

  it("emphasises Cases with Me while it holds something, and no other tile", async () => {
    browserApi(mine());
    renderWithClient(<Dashboard />);
    const files = await screen.findByRole("link", { name: "Cases with Me: 6" });
    expect(files.className).toMatch(/kpiMark/);
    const others = tiles().filter((a) => a !== files);
    expect(others.length).toBeGreaterThanOrEqual(3);
    for (const tile of others) expect(tile.className).not.toMatch(/kpiMark/);
  });

  it("no tile is orange when nothing is with the person", async () => {
    browserApi(mine(personal({ headline: { ...HEADLINE, files_with_me: { total: 0, due_today: 0 } } })));
    renderWithClient(<Dashboard />);
    const files = await screen.findByRole("link", { name: "Cases with Me: 0" });
    expect(files.className).not.toMatch(/kpiMark/);
    for (const tile of tiles()) expect(tile.className).not.toMatch(/kpiMark/);
  });

  it("no department or State tile is emphasised", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    const { container } = renderWithClient(<Dashboard />);
    await screen.findByRole("table", { name: "Cases by Department" });
    expect(container.querySelector('[class*="kpiMark"]')).toBeNull();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardDepartment, DashboardMe, DashboardState } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient } from "@/test/render";

import { Dashboard } from "./Dashboard";
import { dayWords } from "./Headline";

const CASE = { id: "c1", ref_no: "EDU/2026/0001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" };

function department(code: string, name: string, extra: Partial<DashboardDepartment> = {}): DashboardDepartment {
  return {
    department: { code, name },
    generated_at: "2026-10-10T04:30:00Z",
    cases: { claimed_active: 128400, claimed_disposed: 12, not_allotted_active: 3, watching_active: 1 },
    hearings: {
      total: 2,
      critical: 1,
      items: [
        { case: CASE, date: "2026-10-11", court_no: "3", item_no: "14", critical: true },
        { case: { ...CASE, id: "c2", case_no_text: "WA/55/2026" }, date: "2026-10-15", court_no: "5", item_no: "2", critical: false },
      ],
    },
    attention: { compliance_due_soon: 4, compliance_overdue: 1, next_dates_to_review: null, recent_order_next_dates: [] },
    recommendations: { high: 5, medium: 7, transfers_in_open: 2 },
    pending_actions: { held: 9, overdue: 3, due_soon: 2, no_due_date: 1, items: null },
    custody_by_office: [{ office_code: "EDU-DSE", office_name: "Secondary Education", holder_department_code: "EDU", held: 4, with_pending_action: 2, overdue: 1 }],
    ...extra,
  };
}

const PERSONAL: DashboardMe = {
  generated_at: "2026-10-10T04:30:00Z",
  cases: [{ department_code: "EDU", allotted_active: 6, allotted_disposed: 2, counsel_active: null }],
  files: { held: 3, with_pending_action: 2, overdue: 1, items: [] },
  alerts: {
    unread: 2,
    open: { critical: 1, high: 0, normal: 1 },
    items: [
      { id: "a1", ref_no: "ALR-1", kind: "hearing", kind_label: "Hearing", severity: "critical", status: "open", title: "Hearing tomorrow", created_at: "2026-10-10T01:00:00Z", due_at: null, case: CASE, case_visible: true },
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
  await userEvent.click(await screen.findByRole("button", { name: "More about my work" }));
}

describe("dashboard", () => {
  it("shows only the blocks /dashboard names", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": PERSONAL,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My work" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "State overview" })).toBeNull();
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

  it("shows the tiles, the 48-hour badge from critical and the Indian grouping", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: false, state: false, departments: [{ code: "EDU", name: "Education" }] },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByText("1,28,400")).toBeInTheDocument();
    expect(within(block).getByText("Recommendations awaiting review")).toBeInTheDocument();
    const rows = within(block).getAllByRole("row");
    const critical = rows.find((r) => within(r).queryByText("WP(C)/1234/2026"))!;
    expect(within(critical).getByText("Within 48 h")).toBeInTheDocument();
    // case references are links to the case page (design portal-cases, decision 2)
    expect(within(critical).getByRole("link", { name: "WP(C)/1234/2026" })).toHaveAttribute(
      "href",
      "/cases/EDU-2026-0001",
    );
    const later = rows.find((r) => within(r).queryByText("WA/55/2026"))!;
    expect(within(later).getByText("This week")).toBeInTheDocument();
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
    expect(within(block).queryByText("Recommendations awaiting review")).toBeNull();
    expect(within(block).queryByText("Pending actions")).toBeNull();
    expect(within(block).queryByText("Cases by office")).toBeNull();
    expect(within(block).queryByText("Open transfers")).toBeNull();
    expect(within(block).queryByText("Next dates to confirm")).toBeNull();
    expect(within(block).getByText("Hearings in 7 days")).toBeInTheDocument();
  });

  it("one failing view shows its error while the others render", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"]),
      "GET /dashboard": { me: true, departments: [], state: true },
      "GET /dashboard/me": PERSONAL,
      "GET /dashboard/state": json(500, { detail: "boom" }),
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My work" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "State" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/?view=state");
    renderWithClient(<Dashboard params={{ view: "state" }} />);
    const state = await screen.findByRole("region", { name: "State overview" });
    await waitFor(() => expect(within(state).getByText("This block could not be loaded.")).toBeInTheDocument());
    expect(within(state).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("the State block lists departments and the not-claimed row", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    const table = await screen.findByRole("table", { name: "Cases by department" });
    expect(within(table).getByText("Education")).toBeInTheDocument();
    expect(within(table).getByRole("rowheader", { name: "Not claimed" })).toBeInTheDocument();
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
    await screen.findByText("Open tickets");
    const panel = screen.getByRole("region", { name: "Tickets awaiting action" });
    expect(within(panel).getByText("Departments without a head")).toBeInTheDocument();
    expect(await within(panel).findByRole("rowheader", { name: "Head change" })).toBeInTheDocument();
    expect(within(panel).getByRole("rowheader", { name: "EDU" })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open the tickets list" })).toHaveAttribute("href", "/admin/tickets");
    const regions = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
    expect(regions[0]).toBe("Tickets awaiting action");
  });

  it("no ticket panel without a ticket function", async () => {
    const api = browserApi({
      "GET /me": makeMe(["cases.view_scope"]),
      "GET /dashboard": { me: true, departments: [], state: false },
      "GET /dashboard/me": PERSONAL,
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My work" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Tickets awaiting action" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/admin/tickets"))).toBe(false);
  });

  it("a department admin who proposes head changes gets the panel, which says when nothing is open", async () => {
    browserApi({
      "GET /me": makeMe(["users.view", "users.propose_head"], "dept_admin"),
      "GET /admin/tickets/counts": { open: 0, open_by_kind: {}, open_by_department: {}, oldest_open_at: null },
    });
    renderWithClient(<Dashboard />);
    await screen.findByText("No open tickets.");
    const panel = screen.getByRole("region", { name: "Tickets awaiting action" });
    expect(within(panel).queryByText("Departments without a head")).toBeNull();
  });

  it("a login without case functions gets the short page", async () => {
    const api = browserApi({ "GET /me": makeMe(["users.view", "offices.manage"], "dept_admin") });
    renderWithClient(<Dashboard />);
    expect(await screen.findByText("There is no case dashboard for your login.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Administration" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/dashboard")).toBe(false);
  });

  it("links the My alerts heading to /alerts and the Cases with me number to /cases/with-me (case-workspace-admin, decision 21)", async () => {
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
            { id: "a2", ref_no: "ALR-2", kind: "workflow", kind_label: "File movement", severity: "normal", status: "open", title: "File recalled", created_at: "2026-10-10T02:00:00Z", due_at: null, case: hidden, case_visible: false },
          ],
        },
      },
    });
    renderWithClient(<Dashboard />);
    await openMore();
    await screen.findByText(/File recalled/);
    const block = screen.getByRole("region", { name: "My work" });
    expect(within(block).getByRole("link", { name: "My alerts" })).toHaveAttribute("href", "/alerts");
    for (const link of within(block).getAllByRole("link", { name: "Cases with me: 3" })) expect(link).toHaveAttribute("href", "/cases/with-me");
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
    await screen.findByRole("table", { name: "Cases by department" });
    const block = screen.getByRole("region", { name: "State overview" });
    expect(within(block).getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports/pending-cases");
    unmount();
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"], "state_oversight"),
      "GET /dashboard": { me: false, departments: [], state: true },
      "GET /dashboard/state": STATE,
    });
    renderWithClient(<Dashboard />);
    await screen.findByRole("table", { name: "Cases by department" });
    const plain = screen.getByRole("region", { name: "State overview" });
    expect(within(plain).queryByRole("link", { name: "Reports" })).toBeNull();
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
    expect(within(block).getByRole("link", { name: "Department reports" })).toHaveAttribute(
      "href",
      "/reports/pending-cases?department=EDU",
    );
    unmount();
    browserApi({ ...routes, "GET /me": makeMe(["cases.view_scope"]) });
    renderWithClient(<Dashboard />);
    await screen.findByText("1,28,400");
    const plain = screen.getByRole("region", { name: "Department: Education" });
    expect(within(plain).queryByRole("link", { name: "Department reports" })).toBeNull();
  });

  it("Next dates to confirm links to the review list for the department when above zero (portal-next-dates, decision 13)", async () => {
    const att = (n: number | null, recent: DashboardDepartment["attention"]["recent_order_next_dates"] = []) =>
      department("EDU", "Education", {
        attention: { compliance_due_soon: 0, compliance_overdue: 0, next_dates_to_review: n, recent_order_next_dates: recent },
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
    expect(within(block).getByRole("link", { name: "Next dates to confirm" })).toHaveAttribute("href", "/alerts/next-dates?owner=EDU");
    const table = within(block).getByRole("table", { name: "Recent order next dates" });
    expect(within(table).getByRole("columnheader", { name: "Where it came from" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(within(table).getByText("Counted from the order")).toBeInTheDocument();
    expect(within(table).getByText("Waiting for confirmation")).toBeInTheDocument();
    expect(within(table).getByText("Date in the order")).toBeInTheDocument();
    expect(within(table).getByText("In use")).toBeInTheDocument();
    unmount();
    browserApi(routes(att(0)));
    const second = renderWithClient(<Dashboard />);
    block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).getByText("Next dates to confirm")).toBeInTheDocument();
    expect(within(block).queryByRole("link", { name: "Next dates to confirm" })).toBeNull();
    second.unmount();
    browserApi(routes(att(null)));
    renderWithClient(<Dashboard />);
    block = await screen.findByRole("region", { name: "Department: Education" });
    expect(within(block).queryByText("Next dates to confirm")).toBeNull();
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
  { kind: "confirm_next_date", case: { ...CASE, id: "c3", case_no_text: "WA/3/2026" }, title: "Next date to confirm", date: "2026-11-19", detail: "Suggested from an order", pending_action: null, overdue_days: 0, next_date_id: "nd-1" },
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
    expect(await screen.findByRole("heading", { level: 1, name: "Good morning, Anita" })).toBeInTheDocument();
    expect(screen.getByText("Education · Wednesday, 21 October")).toBeInTheDocument();
    unmount();
    vi.setSystemTime(new Date("2026-10-21T09:00:00Z")); // 14:30 IST
    browserApi(mine());
    const second = renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good afternoon, Anita" })).toBeInTheDocument();
    second.unmount();
    vi.setSystemTime(new Date("2026-10-21T13:00:00Z")); // 18:30 IST
    browserApi(mine());
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("heading", { level: 1, name: "Good evening, Anita" })).toBeInTheDocument();
  });

  it("five headline numbers, each a link to its list; a null figure is left out", async () => {
    browserApi(mine());
    const { unmount } = renderWithClient(<Dashboard />);
    const headline = await screen.findByRole("region", { name: "Headline numbers" });
    const links = within(headline).getAllByRole("link");
    expect(links.map((l) => [l.getAttribute("aria-label"), l.getAttribute("href")])).toEqual([
      ["Cases to claim: 12", "/claim/recommended"],
      ["Hearings this week: 4", "/calendar"],
      ["Cases with me: 6", "/cases/with-me"],
      ["Overdue actions: 3", "/cases/with-me?overdue=true"],
      ["Next dates to confirm: 2", "/alerts/next-dates"],
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
    const fewer = await screen.findByRole("region", { name: "Headline numbers" });
    expect(within(fewer).getAllByRole("link")).toHaveLength(3);
    expect(fewer).toHaveAttribute("data-count", "3");
    expect(within(fewer).queryByText("Cases to claim")).toBeNull();
    expect(within(fewer).queryByText("Next dates to confirm")).toBeNull();
  });

  it("under reduced motion the numbers show their final value at once", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
    browserApi(mine());
    renderWithClient(<Dashboard />);
    const headline = await screen.findByRole("region", { name: "Headline numbers" });
    expect(within(headline).getByText("12")).toBeInTheDocument();
    expect(within(headline).getByText("6")).toBeInTheDocument();
  });

  it("Review cases to claim is the one primary, only with cases to claim and Case claim shown", async () => {
    browserApi(mine());
    const { container, unmount } = renderWithClient(<Dashboard />);
    expect(await screen.findByRole("link", { name: "Review cases to claim" })).toHaveAttribute("href", "/claim/recommended");
    expect(container.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
    unmount();
    browserApi(mine(personal({ headline: { ...HEADLINE, to_claim: { high: 0, medium: 0 } } })));
    const none = renderWithClient(<Dashboard />);
    await screen.findByRole("region", { name: "Headline numbers" });
    expect(screen.queryByRole("link", { name: "Review cases to claim" })).toBeNull();
    expect(none.container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("Needs your attention leads every row with a Lead badge and links to the case or the review", async () => {
    browserApi(mine());
    renderWithClient(<Dashboard />);
    const list = await screen.findByRole("list", { name: "Needs your attention" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    for (const row of rows) expect(row.firstElementChild).toHaveAttribute("data-lead", "lead");
    expect(rows.map((r) => r.firstElementChild!.textContent)).toEqual(["Overdue", "Confirm", "Due soon", "New"]);
    expect(within(rows[0]!).getByRole("link", { name: "Parawise comments" })).toHaveAttribute("href", "/cases/EDU-2026-0001");
    expect(within(rows[0]!).getByText("WP(C)/1234/2026 · Overdue 6 days")).toBeInTheDocument();
    expect(within(rows[1]!).getByRole("link", { name: "Next date to confirm" })).toHaveAttribute("href", "/alerts/next-dates?q=c3");
  });

  it("Upcoming hearings lead with the date chip, red within 48 hours, and the day words", async () => {
    vi.useFakeTimers({ now: new Date("2026-10-21T03:00:00Z"), toFake: ["Date"] });
    browserApi(
      mine(
        personal({
          upcoming: [
            { case: CASE, date: "2026-10-22", court_no: "3", item_no: "14", critical: true, this_week: true },
            { case: { ...CASE, id: "c2", case_no_text: "WA/55/2026" }, date: "2026-10-26", court_no: null, item_no: null, critical: false, this_week: true },
          ],
        }),
      ),
    );
    renderWithClient(<Dashboard />);
    const list = await screen.findByRole("list", { name: "Upcoming hearings" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.firstElementChild!.getAttribute("data-lead"))).toEqual(["date", "date"]);
    expect(rows[0]!.firstElementChild!.className).toMatch(/hot/);
    expect(rows[1]!.firstElementChild!.className).not.toMatch(/hot/);
    expect(within(rows[0]!).getByText("Tomorrow")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Court 3 · item 14")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("This week")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open calendar →" })).toHaveAttribute("href", "/calendar");
  });

  it("the view switch shows only with more than one view", async () => {
    browserApi(mine());
    const { unmount } = renderWithClient(<Dashboard />);
    await screen.findByRole("region", { name: "Headline numbers" });
    expect(screen.queryByRole("radiogroup", { name: "Dashboard view" })).toBeNull();
    unmount();
    browserApi({
      ...mine(),
      "GET /dashboard": { me: true, departments: [{ code: "EDU", name: "Education" }], state: false },
      "GET /dashboard/department": department("EDU", "Education"),
    });
    renderWithClient(<Dashboard />);
    const group = await screen.findByRole("radiogroup", { name: "Dashboard view" });
    expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["My work", "Department"]);
    await userEvent.click(within(group).getByRole("radio", { name: "Department" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/?view=department");
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
    expect(screen.queryByRole("region", { name: "My work" })).toBeNull();
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
    expect(await screen.findByRole("table", { name: "Cases by department" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "State" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("region", { name: "My work" })).toBeNull();
  });
});

describe("every Upcoming hearings row has a badge (design portal-ui-polish, decision 14)", () => {
  it("dayWords gives In n days for a hearing in the next calendar week", () => {
    // Saturday 24 Oct 2026, 11:30 IST: Monday 26 Oct (day 2) and Friday 30 Oct (day 6) fall in the next week
    const now = new Date("2026-10-24T06:00:00Z");
    const w = (date: string, critical = false, this_week = false) => dayWords({ date, critical, this_week }, now);
    expect(w("2026-10-24", true, true)).toEqual({ text: "Today", tone: "danger" });
    expect(w("2026-10-25", true, true)).toEqual({ text: "Tomorrow", tone: "danger" });
    expect(w("2026-10-25", false, true)).toEqual({ text: "Tomorrow", tone: undefined });
    expect(w("2026-10-26", true, false)).toEqual({ text: "In 2 days", tone: "danger" });
    expect(dayWords({ date: "2026-10-23", critical: false, this_week: true }, new Date("2026-10-21T06:00:00Z"))).toEqual({
      text: "This week",
    });
    expect(w("2026-10-26")).toEqual({ text: "In 2 days" });
    expect(w("2026-10-30")).toEqual({ text: "In 6 days" });
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
    await screen.findByRole("table", { name: "Cases by department" });
    for (const table of screen.getAllByRole("table")) expectDataTable(table);
  });
});

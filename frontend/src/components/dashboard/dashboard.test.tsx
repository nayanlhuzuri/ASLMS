import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { DashboardDepartment, DashboardMe, DashboardState } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { Dashboard } from "./Dashboard";

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
      { id: "a1", ref_no: "ALR-1", kind: "hearing", kind_label: "Hearing", severity: "critical", status: "open", title: "Hearing tomorrow", created_at: "2026-10-10T01:00:00Z", due_at: null, case: CASE },
    ],
  },
  hearings: { total: 0, critical: 0, items: [] },
  drafts: 1,
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
    expect(within(block).queryByText("Files by office")).toBeNull();
    expect(within(block).queryByText("Open transfers")).toBeNull();
    expect(within(block).queryByText("Next dates to review")).toBeNull();
    expect(within(block).getByText("Hearings in 7 days")).toBeInTheDocument();
  });

  it("one failing block shows its error while the others render", async () => {
    browserApi({
      "GET /me": makeMe(["cases.view_all", "dashboard.state"]),
      "GET /dashboard": { me: true, departments: [], state: true },
      "GET /dashboard/me": PERSONAL,
      "GET /dashboard/state": json(500, { detail: "boom" }),
    });
    renderWithClient(<Dashboard />);
    expect(await screen.findByRole("region", { name: "My work" })).toBeInTheDocument();
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
});

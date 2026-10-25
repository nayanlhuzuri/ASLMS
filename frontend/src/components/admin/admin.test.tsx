import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ExitPreview, MembershipOut, Permission, TicketDetail, UserOut } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { AdminFrame } from "./AdminFrame";
import { Designations } from "./Designations";
import { OfficeDetailView } from "./Offices";
import { TicketView } from "./Tickets";
import { UserDetail } from "./UserDetail";
import { NewUserForm, UsersList } from "./Users";

const MEMBERSHIP: MembershipOut = {
  id: "m-9",
  office: { code: "EDU-DSE", name: "Secondary Education", kind: "directorate" },
  department_code: "EDU",
  designation: "Section Officer",
  role: "directorate_user",
  is_primary: true,
  is_active: true,
};

const USER: UserOut = {
  id: "u-9",
  email: "ravi@example.org",
  full_name: "Ravi Das",
  role: "directorate_user",
  office: { id: "o-2", code: "EDU-DSE", name: "Secondary Education", kind: "directorate", path: "GOA/EDU/EDU-DSE", is_active: true },
  designation: "Section Officer",
  mobile: "9864012345",
  is_active: true,
  must_confirm_profile: false,
  must_change_password: false,
  last_login_at: null,
  created_at: "2026-10-01T00:00:00Z",
  memberships: [MEMBERSHIP],
};

const DEPT_ADMIN: Permission[] = [
  "users.view",
  "users.create",
  "users.edit",
  "users.set_type",
  "users.enable_disable",
  "users.grant",
  "users.reset_password",
  "users.propose_head",
  "offices.manage",
];

function userRoutes(me: ReturnType<typeof makeMe>, extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": me,
    "GET /reference/labels": labels(["dept_officer", "directorate_user", "standing_counsel", "referral_reviewer"]),
    "GET /admin/users/u-9": USER,
    "GET /admin/users/u-9/memberships": [MEMBERSHIP],
    "GET /admin/designations": [],
    ...extra,
  });
}

beforeEach(() => {
  resetNav("/admin/users");
});

describe("user detail", () => {
  it("shows no action without its function", async () => {
    userRoutes(makeMe(["users.view"], "auditor"));
    renderWithClient(<UserDetail id="u-9" />);
    expect(await screen.findByRole("heading", { name: "Ravi Das" })).toBeInTheDocument();
    await screen.findByText("Section Officer");
    for (const name of ["Edit", "Disable Login", "Set a Temporary Password", "End Membership", "Change", "Add a Membership", "Government Orders"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByRole("button", { name: "Functions and Overrides" })).toBeInTheDocument();
  });

  it("shows each action with its function", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"));
    renderWithClient(<UserDetail id="u-9" />);
    await screen.findByRole("heading", { name: "Ravi Das" });
    for (const name of ["Edit", "Disable Login", "Set a Temporary Password", "End Membership", "Change", "Add a Membership", "Government Orders"]) {
      expect(await screen.findByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("the exit dialog lists every item and submits only when each has a successor", async () => {
    const preview: ExitPreview = {
      counts: { allotments: 1, files: 1, drafts: 0, open_alerts: 2 },
      items_fingerprint: "fp-1",
      primary_after: null,
      items: [
        { key: "allotment:1", kind: "allotment", case: { ref_no: "EDU/2026/0001", case_no: "WP(C)/1/2026", cnr: null, court: null, owning_department: "EDU", visible: true }, open_alerts: 1 },
        { key: "file:c2:7", kind: "file", case: { ref_no: "EDU/2026/0002", case_no: "WA/2/2026", cnr: null, court: null, owning_department: "EDU", visible: true }, open_alerts: 1, pending_action: "parawise_comments" },
      ],
      targets: [
        { membership: "m-20", name: "Mira Bora", designation: "Deputy Secretary", office_code: "EDU", role: "dept_officer" },
        { membership: "m-21", name: "Kunal Nath", designation: null, office_code: "EDU-DSE", role: "directorate_user" },
      ],
    };
    const api = userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "GET /admin/users/u-9/memberships/m-9/exit-preview": preview,
      "POST /admin/users/u-9/memberships/m-9/end": { membership: { ...MEMBERSHIP, is_active: false }, reassigned: [], counts: { alerts: 0, allotments: 1, files: 1, notes_finalised: 0 } },
    });
    renderWithClient(<UserDetail id="u-9" />);
    await userEvent.click(await screen.findByRole("button", { name: "End Membership" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("WP(C)/1/2026")).toBeInTheDocument();
    expect(within(dialog).getByText("WA/2/2026")).toBeInTheDocument();
    const submit = within(dialog).getByRole("button", { name: "End Membership" });
    await userEvent.type(within(dialog).getByLabelText("Reason for Ending"), "transferred out");
    expect(submit).toBeDisabled();
    expect(within(dialog).getByText("2 item(s) still need a successor.")).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("Successor EDU/2026/0001"), "m-20");
    expect(submit).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByLabelText("Successor EDU/2026/0002"), "m-21");
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path.endsWith("/end"))).toBe(true));
    const body = api.calls.find((c) => c.path.endsWith("/end"))!.body;
    expect(body).toEqual({
      reason: "transferred out",
      items_fingerprint: "fp-1",
      assignments: [
        { key: "allotment:1", to_membership: "m-20" },
        { key: "file:c2:7", to_membership: "m-21" },
      ],
    });
  });

  it("the change dialog offers only the assignable types", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"));
    renderWithClient(<UserDetail id="u-9" />);
    await userEvent.click(await screen.findByRole("button", { name: "Change" }));
    const dialog = await screen.findByRole("dialog");
    const options = within(within(dialog).getByLabelText("User Type")).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options.sort()).toEqual(["dept_officer", "directorate_user", "referral_reviewer", "standing_counsel"]);
  });
});

describe("new user", () => {
  it("the e-mail lookup offers a membership instead of a duplicate", async () => {
    const api = browserApi({
      "GET /reference/labels": labels(["dept_officer"]),
      "GET /admin/designations": [],
      "GET /admin/users/lookup": { id: "u-5", full_name: "Mira Bora", memberships: [{ office_code: "HEALTH", designation: "JS", role: "dept_officer" }] },
      "POST /admin/users/u-5/memberships": { ...MEMBERSHIP, id: "m-50" },
    });
    renderWithClient(<NewUserForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "mira@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    expect(await screen.findByText("Mira Bora already has a login.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create User" })).toBeNull();
    await userEvent.type(screen.getByLabelText("Office Code"), "EDU");
    await userEvent.selectOptions(screen.getByLabelText("User Type"), "dept_officer");
    await userEvent.click(screen.getByRole("button", { name: "Add a Membership to This Person" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/admin/users/u-5"));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ office: "EDU", designation: null, role: "dept_officer" });
  });

  it("an unknown e-mail offers the creation form with only assignable types", async () => {
    browserApi({
      "GET /reference/labels": labels(["dept_officer", "directorate_user"]),
      "GET /admin/designations": [],
      "GET /admin/users/lookup": json(404, { detail: "no such user" }),
    });
    renderWithClient(<NewUserForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "new@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    expect(await screen.findByRole("button", { name: "Create User" })).toBeInTheDocument();
    const values = within(screen.getByLabelText("User Type"))
      .getAllByRole("option")
      .map((o) => o.getAttribute("value"))
      .filter(Boolean);
    expect(values).toEqual(["dept_officer", "directorate_user"]);
  });
});

describe("the Users list on the Settings hub (case-workspace-admin, decision 23)", () => {
  const OFF: UserOut = { ...USER, id: "u-10", full_name: "Off Person", email: "off@example.org", is_active: false, last_login_at: null };
  const ACTIVE: UserOut = {
    ...USER,
    id: "u-11",
    full_name: "Mira Bora",
    email: "mira@example.org",
    last_login_at: "2026-10-20T10:00:00Z",
    memberships: [
      { ...MEMBERSHIP, id: "m-11", role: "dept_officer", designation: "Under Secretary", office: { code: "EDU", name: "Education", kind: "department" } },
      { ...MEMBERSHIP, id: "m-12", role: "standing_counsel", is_primary: false },
      { ...MEMBERSHIP, id: "m-13", role: "referral_reviewer", is_primary: false },
    ],
  };

  it("rows show the initials, the name over the post, the type badges with +n and the status", async () => {
    browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER, OFF, ACTIVE], { "x-total-count": "3" }),
    });
    renderWithClient(<UsersList />);
    const table = await screen.findByRole("table", { name: "Users" });
    const row = (name: string) => within(table).getByText(name).closest("tr")!;
    expect(within(row("Ravi Das")).getByText("RD")).toHaveAttribute("data-lead", "avatar");
    expect(within(row("Ravi Das")).getByText("Section Officer, Secondary Education")).toBeInTheDocument();
    expect(within(row("Ravi Das")).getByText("Not Signed in Yet")).toBeInTheDocument();
    expect(within(row("Off Person")).getByText("Off")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Active")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Under Secretary, Education")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Dept officer")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Standing counsel")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("+1")).toBeInTheDocument();
    expectDataTable(table);
  });

  it("the Status filter sends status and the other filters stay as they were", async () => {
    const api = browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
    });
    renderWithClient(<UsersList />);
    await screen.findByRole("table", { name: "Users" });
    const status = screen.getByLabelText("Status");
    expect(within(status).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any Status", "Active", "Not Signed in Yet", "Off"]);
    await userEvent.selectOptions(status, "not_signed_in");
    await userEvent.type(screen.getByLabelText("Name or E-mail"), "ra");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.calls.some((c) => c.path.includes("status=not_signed_in"))).toBe(true));
    const url = api.calls.filter((c) => c.path.startsWith("/admin/users?")).pop()!.path;
    expect(url).toContain("q=ra");
    expect(url).toContain("limit=50");
  });

  it("a row opens the side panel on ?user=<id> with the user's sections and Open full page", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), { "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }) });
    const { unmount } = renderWithClient(<UsersList />);
    await userEvent.click(await screen.findByRole("row", { name: "Open Ravi Das" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users?user=u-9");
    unmount();
    resetNav("/admin/users", "user=u-9");
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), { "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }) });
    renderWithClient(<UsersList params={{ user: "u-9" }} />);
    const panel = await screen.findByRole("dialog", { name: "Ravi Das" });
    expect(panel).toHaveAttribute("data-panel", "wide");
    expect(await within(panel).findByRole("region", { name: "Offices (Memberships)" })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open Full Page" })).toHaveAttribute("href", "/admin/users/u-9");
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(nav.replace).toHaveBeenCalledWith("/admin/users");
  });

  it("Add user opens the new-user flow in the panel; a created login opens its own panel", async () => {
    const api = userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
      "GET /admin/users/lookup": json(404, { detail: "no such user" }),
      "POST /admin/users": { ...USER, id: "u-20" },
    });
    const { unmount } = renderWithClient(<UsersList />);
    await userEvent.click(await screen.findByRole("button", { name: "Add User" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users?user=new");
    unmount();
    resetNav("/admin/users", "user=new");
    renderWithClient(<UsersList params={{ user: "new" }} />);
    const panel = await screen.findByRole("dialog", { name: "Add User" });
    await userEvent.type(within(panel).getByLabelText("E-mail"), "new@example.org");
    await userEvent.click(within(panel).getByRole("button", { name: "Check E-mail" }));
    await userEvent.type(await within(panel).findByLabelText("Full Name"), "New Person");
    await userEvent.type(within(panel).getByLabelText("Temporary Password"), "Str0ng!Passw0rd");
    await userEvent.type(within(panel).getByLabelText("Office Code"), "EDU");
    await userEvent.selectOptions(within(panel).getByLabelText("User Type"), "dept_officer");
    await userEvent.click(within(panel).getByRole("button", { name: "Create User" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/admin/users?user=u-20"));
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/admin/users")).toBe(true);
  });
});

describe("tickets", () => {
  function ticket(extra: Partial<TicketDetail>): TicketDetail {
    return {
      ref_no: "TKT/EDU/2026/0001",
      kind: "head_change",
      operation: "replace",
      status: "open",
      department_code: "EDU",
      age_days: 2,
      created_at: "2026-10-08T05:00:00Z",
      decided_at: null,
      decided_by: null,
      decision_remark: null,
      request_remark: "order dated 1 Oct",
      requested_by: { name: "Edu Admin", designation: null, office_code: "EDU" },
      target: { user_name: "Mira Bora", designation: "Commissioner", role_from: "dept_officer", role_to: "dept_head" },
      documents: [],
      documents_count: 0,
      payload: {},
      outgoing_detail: null,
      result: null,
      can_approve: false,
      can_withdraw: false,
      can_attach: false,
      ...extra,
    };
  }

  it("approve and reject only when the server says so (the super admin)", async () => {
    browserApi({ "GET /reference/labels": labels(), "GET /admin/tickets/TKT-EDU-2026-0001": ticket({ can_approve: true }) });
    renderWithClient(<TicketView ticketRef="TKT-EDU-2026-0001" />);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled(); // a remark is required first
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
  });

  it("withdraw only for the proposer", async () => {
    browserApi({ "GET /reference/labels": labels(), "GET /admin/tickets/TKT-EDU-2026-0001": ticket({ can_withdraw: true }) });
    renderWithClient(<TicketView ticketRef="TKT-EDU-2026-0001" />);
    expect(await screen.findByRole("button", { name: "Withdraw" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("neither for anyone else", async () => {
    browserApi({ "GET /reference/labels": labels(), "GET /admin/tickets/TKT-EDU-2026-0001": ticket({}) });
    renderWithClient(<TicketView ticketRef="TKT-EDU-2026-0001" />);
    await screen.findByText("Mira Bora, Commissioner (Dept officer → Dept head)");
    for (const name of ["Approve", "Reject", "Withdraw"]) expect(screen.queryByRole("button", { name })).toBeNull();
  });
});

describe("offices", () => {
  it("deactivate shows the API's dependency counts on 409", async () => {
    browserApi({
      "GET /me": makeMe(["users.view", "offices.manage"], "super_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/offices/EDU-DSE": {
        id: "o-2",
        code: "EDU-DSE",
        name: "Secondary Education",
        kind: "directorate",
        tier: "directorate",
        path: "GOA/EDU/EDU-DSE",
        depth: 2,
        parent_code: "EDU",
        is_active: true,
        notes: null,
        counts: { children: 0, users: 3, ownership: 0, custody: 2 },
        created_at: "2026-10-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
        deactivated_at: null,
        valid_from: "2026-10-01",
        valid_to: null,
      },
      "POST /admin/offices/EDU-DSE/deactivate": json(409, {
        detail: { message: "the office is still in use", counts: { users: 3, custody: 2 } },
      }),
    });
    renderWithClient(<OfficeDetailView code="EDU-DSE" />);
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    expect(await screen.findByText("The office is still in use:")).toBeInTheDocument();
    expect(screen.getByText("users: 3")).toBeInTheDocument();
    expect(screen.getByText("custody: 2")).toBeInTheDocument();
  });
});

describe("audit links (portal-audit-health, decision 7)", () => {
  function superAdmin(functions: Permission[]) {
    return makeMe(functions, "super_admin", {
      memberships: [
        {
          id: "m-1",
          office: { code: "GOA", name: "Government of Assam", kind: "state" },
          department_code: null,
          designation: null,
          role: "super_admin",
          is_primary: true,
          is_active: true,
          functions,
        },
      ],
    });
  }
  const OFFICE = {
    id: "o-2",
    code: "EDU-DSE",
    name: "Secondary Education",
    kind: "directorate",
    tier: "directorate",
    path: "GOA/EDU/EDU-DSE",
    depth: 2,
    parent_code: "EDU",
    is_active: true,
    notes: null,
    counts: { children: 0, users: 3, ownership: 0, custody: 2 },
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    deactivated_at: null,
    valid_from: "2026-10-01",
    valid_to: null,
  };

  it("a user's page links to the entries by and about the user for an audit reader", async () => {
    userRoutes(superAdmin(["users.view", "audit.view", "cases.view_all"]));
    renderWithClient(<UserDetail id="u-9" />);
    expect(await screen.findByRole("link", { name: "Entries by This User" })).toHaveAttribute("href", "/audit?user=u-9");
    expect(screen.getByRole("link", { name: "Entries About This User" })).toHaveAttribute("href", "/audit?about_user=u-9");
  });

  it("no audit links on a user's page without readsAudit", async () => {
    userRoutes(makeMe([...DEPT_ADMIN, "audit.view"], "dept_admin"));
    renderWithClient(<UserDetail id="u-9" />);
    await screen.findByRole("heading", { name: "Ravi Das" });
    expect(screen.queryByRole("link", { name: "Entries by This User" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Entries About This User" })).toBeNull();
  });

  it("an office's page links to the entries by the office for an audit reader, not otherwise", async () => {
    browserApi({
      "GET /me": superAdmin(["users.view", "offices.manage", "audit.view", "cases.view_all"]),
      "GET /reference/labels": labels(),
      "GET /admin/offices/EDU-DSE": OFFICE,
    });
    const { unmount } = renderWithClient(<OfficeDetailView code="EDU-DSE" />);
    expect(await screen.findByRole("link", { name: "Entries by This Office" })).toHaveAttribute(
      "href",
      "/audit?office=EDU-DSE",
    );
    unmount();
    browserApi({
      "GET /me": makeMe(["users.view", "offices.manage", "audit.view"], "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/offices/EDU-DSE": OFFICE,
    });
    renderWithClient(<OfficeDetailView code="EDU-DSE" />);
    await screen.findByRole("heading", { name: /Secondary Education/ });
    expect(screen.queryByRole("link", { name: "Entries by This Office" })).toBeNull();
  });
});

describe("Administration on the Settings template (design portal-ui-redesign, decision 26)", () => {
  it("the groups are a sub-menu by function with the current one marked, and a select for phones", async () => {
    resetNav("/admin/offices/EDU");
    browserApi({ "GET /me": makeMe([...DEPT_ADMIN, "admin.keywords"], "dept_admin") });
    renderWithClient(<AdminFrame>body</AdminFrame>);
    const menu = await screen.findByRole("navigation", { name: "Administration Sections" });
    expect(within(menu).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "Users",
      "User Types",
      "Offices",
      "Designations",
      "Department Mapping",
      "Tickets",
    ]);
    expect(within(menu).getByRole("link", { name: "Offices" })).toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("link", { name: "Users" })).not.toHaveAttribute("aria-current");
    const select = screen.getByLabelText("Setting Group");
    expect(select).toHaveValue("offices");
    await userEvent.selectOptions(select, "mapping");
    expect(nav.push).toHaveBeenCalledWith("/admin/mapping");
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("a login with no group sees the body alone", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]) });
    renderWithClient(<AdminFrame>nothing here</AdminFrame>);
    expect(await screen.findByText("nothing here")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Administration Sections" })).toBeNull();
  });

  it("the users group keeps one primary (Add user); the filter's Search is secondary", async () => {
    browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
    });
    const { container } = renderWithClient(<UsersList />);
    await screen.findByRole("row", { name: "Open Ravi Das" });
    expect(primaryActions(container)).toEqual(["Add User"]);
    expect(screen.getByRole("button", { name: "Search" })).toHaveAttribute("data-variant", "secondary");
  });

  it("a disabled login's Enable is secondary, so editing it keeps one primary", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), { "GET /admin/users/u-9": { ...USER, is_active: false } });
    const { container } = renderWithClient(<UserDetail id="u-9" />);
    await screen.findByRole("heading", { name: "Ravi Das" });
    expect(screen.getByRole("button", { name: "Enable Login" })).toHaveAttribute("data-variant", "secondary");
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(primaryActions(container)).toEqual(["Save"]);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {

  it("Designations renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(["users.view", "admin.designations"], "super_admin"),
      "GET /admin/designations": [{ id: "d-1", code: "US", name: "Under Secretary to the Government of Assam, Education", sort_order: 10, is_active: true }],
    });
    renderWithClient(<Designations />);
    expectDataTable(await screen.findByRole("table", { name: "Designations" }));
  });

  it("UserDetail renders a DataTable with a primary cell", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "GET /admin/permissions": [{ code: "users.view", module: "users", label: "View users", description: null, is_active: true }],
      "GET /admin/users/u-9/memberships/m-9/permissions": {
        membership_id: "m-9",
        role: "directorate_user",
        type_functions: ["users.view"],
        overrides: [],
        effective: ["users.view"],
      },
      "GET /admin/users/u-9/memberships/m-9/documents": [
        { id: "doc-1", ref_no: "GO/2026/1", doc_date: "2026-10-01", description: "Posting order", doc_type: "order", archived: false, ticket_ref: null, attached_at: "2026-10-01T05:00:00Z", attached_by: null },
      ],
    });
    renderWithClient(<UserDetail id="u-9" />);
    expectDataTable(await screen.findByRole("table", { name: "Offices (Memberships)" }));
    await userEvent.click(screen.getByRole("button", { name: "Functions and Overrides" }));
    expectDataTable(await screen.findByRole("table", { name: "Functions" }));
    await userEvent.click(screen.getByRole("button", { name: "Government Orders" }));
    expectDataTable(await screen.findByRole("table", { name: "Government Orders" }));
  });

  it("Tickets renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /reference/labels": labels(),
      "GET /admin/tickets/TKT-EDU-2026-0001": {
        ref_no: "TKT/EDU/2026/0001",
        kind: "head_change",
        operation: "replace",
        status: "open",
        department_code: "EDU",
        age_days: 2,
        created_at: "2026-10-08T05:00:00Z",
        decided_at: null,
        decided_by: null,
        decision_remark: null,
        request_remark: "order dated 1 Oct",
        requested_by: { name: "Edu Admin", designation: null, office_code: "EDU" },
        target: { user_name: "Mira Bora", designation: "Commissioner", role_from: "dept_officer", role_to: "dept_head" },
        documents: [
          { id: "doc-1", description: "Government order", original_filename: "go.pdf", doc_type: "order", doc_date: "2026-10-01", archived: false },
        ],
        documents_count: 1,
        payload: {},
        outgoing_detail: null,
        result: null,
        can_approve: false,
        can_withdraw: false,
        can_attach: false,
      } as unknown as TicketDetail,
    });
    renderWithClient(<TicketView ticketRef="TKT-EDU-2026-0001" />);
    expectDataTable(await screen.findByRole("table", { name: "Government Orders" }));
  });
});

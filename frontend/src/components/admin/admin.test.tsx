import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { MembershipOut, Permission, TicketDetail, UserOut } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { AdminFrame } from "./AdminFrame";
import { Designations } from "./Designations";
import { NewOfficeForm, OfficeDetailView } from "./Offices";
import { TicketView } from "./Tickets";
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

const CHOICES = {
  purpose: "membership",
  items: [
    { code: "EDU", name: "Education", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
    { code: "EDU-DSE", name: "Secondary Education", kind: "directorate", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: ["Government of Assam", "Education"], is_active: true },
  ],
};

/** Opens an Office Picker and chooses the office by its name. */
async function chooseOffice(box: HTMLElement, name: string) {
  await userEvent.click(box);
  await userEvent.click(within(await screen.findByRole("listbox")).getByText(name));
}

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

describe("new user", () => {
  it("the e-mail lookup offers a membership instead of a duplicate", async () => {
    const api = browserApi({
      "GET /reference/labels": labels(["dept_officer"]),
      "GET /admin/designations": [],
      "GET /admin/users/lookup": { id: "u-5", full_name: "Mira Bora", memberships: [{ office_code: "HEALTH", designation: "JS", role: "dept_officer" }] },
      "GET /admin/offices/choices": CHOICES,
      "POST /admin/users/u-5/memberships": { ...MEMBERSHIP, id: "m-50" },
    });
    renderWithClient(<NewUserForm />);
    await userEvent.type(screen.getByLabelText("E-mail"), "mira@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    expect(await screen.findByText("Mira Bora already has a login.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create User" })).toBeNull();
    await chooseOffice(screen.getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.selectOptions(screen.getByLabelText("User Type"), "dept_officer");
    await userEvent.click(screen.getByRole("button", { name: "Add a Membership to This Person" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/admin/users/u-5"));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ office: "EDU", designation: null, role: "dept_officer" });
    // the picker asks for the offices a membership may be added in
    expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=membership")).toBe(true);
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
    expect(within(row("Off Person")).getByText("Sign-in Off")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Active")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Under Secretary, Education")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Dept officer")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("Standing counsel")).toBeInTheDocument();
    expect(within(row("Mira Bora")).getByText("+1")).toBeInTheDocument();
    expectDataTable(table);
  });

  it("the toolbar is one line: hidden labels, the picker with Include Sub-offices, Status and Search; the filters go to the address", async () => {
    browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
      "GET /admin/offices/choices": { ...CHOICES, purpose: "users" },
    });
    const { container } = renderWithClient(<UsersList />);
    await screen.findByRole("table", { name: "Users" });
    const form = screen.getByRole("search", { name: "Users" });
    // every field of the line sits in the one toolbar line, labels kept for screen readers only
    const line = form.firstElementChild!;
    expect(within(line as HTMLElement).getByLabelText("Name or E-mail")).toHaveAttribute("placeholder", "Name or e-mail");
    for (const name of ["Name or E-mail", "User Type", "Office", "Status"]) {
      const label = [...container.querySelectorAll("label")].find((l) => l.textContent === name)!;
      expect(label).toHaveClass("visually-hidden");
    }
    expect(within(line as HTMLElement).getByRole("combobox", { name: "Office" })).toBeInTheDocument();
    expect(within(line as HTMLElement).getByRole("button", { name: "Search" })).toBeInTheDocument();
    // the 2-character hint is a tooltip
    expect(screen.getByLabelText("Name or E-mail")).toHaveAttribute("title", "Enter at least 2 characters.");
    const status = screen.getByLabelText("Status");
    expect(within(status).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any Status", "Active", "Not Signed in Yet", "Sign-in Off"]);
    // a department admin has nothing under More Filters, so no More Filters button
    expect(screen.queryByRole("button", { name: /More Filters/ })).toBeNull();
    await userEvent.selectOptions(status, "not_signed_in");
    await userEvent.type(screen.getByLabelText("Name or E-mail"), "ra");
    await userEvent.click(screen.getByRole("combobox", { name: "Office" }));
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Education"));
    await userEvent.click(screen.getByLabelText("Include Sub-offices"));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users?q=ra&office=EDU&subtree=false&status=not_signed_in");
  });

  it("the list reads its filters from the address and sends office and subtree", async () => {
    const api = browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
      "GET /admin/offices/choices": { ...CHOICES, purpose: "users" },
    });
    renderWithClient(<UsersList params={{ q: "ra", office: "EDU", subtree: "false", status: "not_signed_in" }} />);
    await screen.findByRole("table", { name: "Users" });
    const url = api.calls.filter((c) => c.path.startsWith("/admin/users?")).pop()!.path;
    for (const part of ["q=ra", "office=EDU", "subtree=false", "status=not_signed_in", "limit=50"]) expect(url).toContain(part);
    expect(screen.getByLabelText("Name or E-mail")).toHaveValue("ra");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Office" })).toHaveValue("Education"));
    expect(screen.getByLabelText("Include Sub-offices")).not.toBeChecked();
  });

  it("More Filters (n) holds Include Logins Without an Active Office for the super admin, with its count", async () => {
    const api = browserApi({
      "GET /me": makeMe([...DEPT_ADMIN, "cases.view_all"], "super_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
      "GET /admin/offices/choices": { ...CHOICES, purpose: "users" },
    });
    renderWithClient(<UsersList />);
    await screen.findByRole("table", { name: "Users" });
    const more = screen.getByRole("button", { name: "More Filters" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(more.getAttribute("aria-controls")!)).not.toBeVisible();
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByLabelText("Include Logins Without an Active Office"));
    expect(screen.getByRole("button", { name: "More Filters (1)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users?include_ended=true");
    expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=users")).toBe(true);
  });

  it("a row opens the person's User Details at /admin/users/<id>, the list's filters kept", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), { "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }) });
    renderWithClient(<UsersList params={{ status: "active" }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open Ravi Das" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users/u-9?status=active");
  });

  it("Add user opens the new-user flow in the panel; a created login opens its User Details", async () => {
    const api = userRoutes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
      "GET /admin/users/lookup": json(404, { detail: "no such user" }),
      "POST /admin/users": { ...USER, id: "u-20" },
      "GET /admin/offices/choices": CHOICES,
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
    await chooseOffice(within(panel).getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.selectOptions(within(panel).getByLabelText("User Type"), "dept_officer");
    await userEvent.click(within(panel).getByRole("button", { name: "Create User" }));
    // the new-user entry is replaced, so Back from the person's details returns to the list
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/admin/users/u-20"));
    expect(api.calls.find((c) => c.method === "POST" && c.path === "/admin/users")!.body).toMatchObject({ office_code: "EDU" });
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
  it("New Office chooses its parent from the Office Picker (purpose office_parent), pre-set from ?parent=", async () => {
    resetNav("/admin/offices/new", "parent=EDU");
    const api = browserApi({
      "GET /me": makeMe(DEPT_ADMIN, "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/offices/choices": { ...CHOICES, purpose: "office_parent" },
      "POST /admin/offices": { code: "EDU-NEW" },
    });
    renderWithClient(<NewOfficeForm />);
    const parent = screen.getByRole("combobox", { name: "Parent Office" });
    await waitFor(() => expect(parent).toHaveValue("Education"));
    await chooseOffice(parent, "Secondary Education");
    await userEvent.type(screen.getByLabelText("Code"), "EDU-NEW");
    await userEvent.type(screen.getByLabelText("Name"), "New Cell");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "directorate");
    await userEvent.click(screen.getByRole("button", { name: "Create Office" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ parent_code: "EDU-DSE" });
    expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=office_parent")).toBe(true);
  });

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

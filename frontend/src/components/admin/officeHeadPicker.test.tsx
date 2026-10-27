/**
 * The head of a department chosen from current logins, and logins with no office yet (design office-head-picker,
 * "Tests"): New Office and Reactivate send `{user_id, designation_id, designation}` with no new-login field and keep
 * the draft for "Not in ASLMS Yet?"; the head-change request names a member by membership and anyone else by e-mail;
 * New User's No Office Yet; the Users list badge and filter; User Details' line and empty state; the dashboard card.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { NoDashboard } from "@/components/dashboard/Dashboard";
import type { MembershipOut, Permission, UserOut } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { NewOfficeForm, OFFICE_DRAFT_KEY, OfficeDetailView } from "./Offices";
import { NewTicketForm } from "./Tickets";
import { NewUserForm, UsersList } from "./Users";

const SUPER_FNS: Permission[] = ["users.view", "users.create", "users.edit", "offices.manage", "admin.tickets", "users.propose_head", "admin.designations"];
const ADMIN_FNS: Permission[] = ["users.view", "users.create", "users.propose_head", "offices.manage"];

function superAdmin(functions: Permission[] = SUPER_FNS) {
  return makeMe(functions, "super_admin", {
    memberships: [
      {
        id: "m-root",
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

function deptAdmin() {
  return makeMe(ADMIN_FNS, "dept_admin", {
    memberships: [
      {
        id: "m-adm",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: null,
        role: "dept_admin",
        is_primary: true,
        is_active: true,
        functions: ADMIN_FNS,
      },
    ],
  });
}

function m(id: string, code: string, role: MembershipOut["role"], extra: Partial<MembershipOut> = {}): MembershipOut {
  return { id, office: { code, name: code, kind: "department" }, department_code: code, designation: null, role, is_primary: true, is_active: true, ...extra };
}

function user(id: string, name: string, email: string, memberships: MembershipOut[], extra: Partial<UserOut> = {}): UserOut {
  return {
    id,
    email,
    full_name: name,
    role: memberships[0]?.role ?? null,
    office: memberships[0] ? { id: "o", code: memberships[0].office.code, name: memberships[0].office.code, kind: "department", path: "GOA/x", is_active: true } : null,
    designation: null,
    mobile: null,
    is_active: true,
    must_confirm_profile: false,
    must_change_password: false,
    last_login_at: null,
    created_at: "2026-10-26T00:00:00Z",
    memberships,
    ...extra,
  };
}

const RAVI = user("u-1", "Ravi Das", "ravi@example.org", [m("m-1", "HEALTH", "dept_officer")]);
const RANI = user("u-2", "Rani Bora", "rani@example.org", []);
const EDU_OFFICER = user("u-3", "Raju Deka", "raju@example.org", [m("m-3", "EDU", "dept_officer")]);
const DSE_USER = user("u-4", "Rama Nath", "rama@example.org", [m("m-4", "EDU-DSE", "directorate_user", { department_code: "EDU" })]);
const EDU_ADMIN = user("u-5", "Rabin Admin", "rabin@example.org", [m("m-5", "EDU", "dept_admin")]);
const PEOPLE = [RAVI, RANI, EDU_OFFICER, DSE_USER, EDU_ADMIN];

const DESIGNATIONS = [
  { id: "d-sec", code: "SEC", name: "Secretary", sort_order: 50, is_active: true },
  { id: "d-ps", code: "PS", name: "Principal Secretary", sort_order: 30, is_active: true },
];

const CHOICES = {
  items: [
    { code: "GOA", name: "Government of Assam", kind: "state", tier: "state", depth: 0, parent_code: null, ancestors: [], is_active: true },
    { code: "EDU", name: "Education", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
    { code: "HEALTH", name: "Health", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
  ],
};

function routes(me: ReturnType<typeof makeMe>, extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": me,
    "GET /reference/labels": labels(["dept_officer", "directorate_user", "standing_counsel", "referral_reviewer"]),
    "GET /admin/designations": DESIGNATIONS,
    "GET /admin/offices/choices": (call: { path: string }) => ({ purpose: new URL(call.path, "http://x").searchParams.get("purpose"), ...CHOICES }),
    "GET /admin/users": (call: { path: string }) => {
      const q = new URL(call.path, "http://x").searchParams;
      if (q.get("role") === "dept_head") return json(200, [], { "x-total-count": "0" });
      return json(200, PEOPLE, { "x-total-count": String(PEOPLE.length) });
    },
    ...extra,
  });
}

async function pick(label: string, text: string, name: string) {
  const box = screen.getByRole("combobox", { name: label });
  await userEvent.type(box, text);
  const option = await screen.findByRole("option", { name: new RegExp(name) });
  await userEvent.click(option);
}

beforeEach(() => {
  resetNav("/admin/offices/new");
  window.sessionStorage.clear();
});

describe("New Office with a Department-tier kind (decisions 1, 4, 8, 11)", () => {
  it("has no new-login field, needs a person and a designation, and sends {user_id, designation_id, designation}", async () => {
    const api = routes(superAdmin(), { "POST /admin/offices": { code: "AGRI" } });
    renderWithClient(<NewOfficeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "agri");
    await userEvent.type(screen.getByLabelText("Name"), "Agriculture");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "department");
    const section = screen.getByRole("region", { name: "Head of the Department" });
    expect(within(section).getByRole("heading", { name: "Head of the Department" })).toBeInTheDocument();
    expect(section.querySelector("fieldset")).toBeNull();
    for (const gone of ["Temporary Password", "Full Name", "E-mail", "Mobile"]) expect(within(section).queryByLabelText(gone)).toBeNull();
    const create = screen.getByRole("button", { name: "Create Office" });
    expect(create).toBeDisabled();
    await pick("Person", "ra", "Rani Bora");
    expect(create).toBeDisabled();
    await waitFor(() => expect(within(screen.getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText("Designation in This Department"), "d-ps");
    expect(create).toBeEnabled();
    await userEvent.click(create);
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const body = api.calls.find((c) => c.method === "POST")!.body as Record<string, unknown>;
    expect(body.head).toEqual({ user_id: "u-2", designation_id: "d-ps", designation: "Principal Secretary" });
    expect(api.calls.some((c) => c.path.startsWith("/admin/users?q=ra&limit=20&include_ended=true"))).toBe(true);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/admin/offices/AGRI"));
  });

  it("the link keeps the draft and goes to New User with No Office Yet; coming back restores it and picks the person", async () => {
    routes(superAdmin(), { "GET /admin/users/u-9": user("u-9", "Nirmal New", "nirmal@example.org", []) });
    const { unmount } = renderWithClient(<NewOfficeForm />);
    await userEvent.type(screen.getByLabelText("Code"), "AGRI");
    await userEvent.type(screen.getByLabelText("Name"), "Agriculture");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "department");
    await waitFor(() => expect(within(screen.getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText("Designation in This Department"), "d-sec");
    const link = screen.getByRole("link", { name: "Not in ASLMS Yet? Add a New User in Users" });
    // office-head-picker-followups, decision 1: the link keeps the draft under ?draft=1
    expect(link).toHaveAttribute("href", "/admin/users/new?no_office=1&return=%2Fadmin%2Foffices%2Fnew%3Fdraft%3D1");
    link.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(link);
    const kept = JSON.parse(window.sessionStorage.getItem(OFFICE_DRAFT_KEY) ?? "{}");
    expect(kept).toMatchObject({ code: "AGRI", name: "Agriculture", kind: "department", designationId: "d-sec" });
    expect(Object.keys(kept).some((k) => /password/i.test(k))).toBe(false);
    // the current history entry is replaced, so Back from New User lands on the marked address
    expect(window.location.pathname + window.location.search).toBe("/admin/offices/new?draft=1");
    window.history.replaceState(null, "", "/");
    unmount();
    // back from New User restores the draft and picks the person
    resetNav("/admin/offices/new", "draft=1&head=u-9");
    renderWithClient(<NewOfficeForm />);
    expect(screen.getByLabelText("Code")).toHaveValue("AGRI");
    expect(screen.getByLabelText("Name")).toHaveValue("Agriculture");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Person" })).toHaveValue("Nirmal New"));
    expect(screen.getByText("No Office Yet")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Designation in This Department")).toHaveValue("d-sec"));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(window.sessionStorage.getItem(OFFICE_DRAFT_KEY)).toBeNull();
  });

  it("a directorate kind shows no head section", async () => {
    routes(superAdmin());
    renderWithClient(<NewOfficeForm />);
    await waitFor(() => expect(within(screen.getByLabelText("Kind")).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "directorate");
    expect(screen.queryByRole("region", { name: "Head of the Department" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Person" })).toBeNull();
  });
});

describe("the kept draft (office-head-picker-followups, decisions 1-3)", () => {
  const DRAFT = { code: "OLD", name: "Old Draft", kind: "department", parent: "AGR", validFrom: "", notes: "", designationId: "d-sec" };

  async function parentShows(name: string) {
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Parent Office" })).toHaveValue(name));
  }

  it("a stale draft never beats ?parent=", async () => {
    window.sessionStorage.setItem(OFFICE_DRAFT_KEY, JSON.stringify(DRAFT));
    resetNav("/admin/offices/new", "parent=EDU");
    routes(superAdmin());
    renderWithClient(<NewOfficeForm />);
    await parentShows("Education");
    expect(screen.getByLabelText("Code")).toHaveValue("");
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Kind")).toHaveValue("");
    expect(window.sessionStorage.getItem(OFFICE_DRAFT_KEY)).toBeNull();
  });

  it("Back or Cancel restores without a person", async () => {
    window.sessionStorage.setItem(OFFICE_DRAFT_KEY, JSON.stringify({ ...DRAFT, parent: "HEALTH" }));
    resetNav("/admin/offices/new", "draft=1");
    const api = routes(superAdmin());
    renderWithClient(<NewOfficeForm />);
    expect(screen.getByLabelText("Code")).toHaveValue("OLD");
    expect(screen.getByLabelText("Name")).toHaveValue("Old Draft");
    await parentShows("Health");
    await waitFor(() => expect(screen.getByLabelText("Designation in This Department")).toHaveValue("d-sec"));
    expect(screen.getByRole("combobox", { name: "Person" })).toHaveValue("");
    expect(api.calls.some((c) => /^\/admin\/users\/[^?]/.test(c.path))).toBe(false);
  });

  it("the address parent wins inside a draft", async () => {
    window.sessionStorage.setItem(OFFICE_DRAFT_KEY, JSON.stringify(DRAFT));
    resetNav("/admin/offices/new", "draft=1&parent=EDU");
    routes(superAdmin());
    renderWithClient(<NewOfficeForm />);
    expect(screen.getByLabelText("Code")).toHaveValue("OLD");
    await parentShows("Education");
  });

  it("with ?draft=1 and nothing stored, the form starts empty", async () => {
    resetNav("/admin/offices/new", "draft=1");
    routes(superAdmin());
    renderWithClient(<NewOfficeForm />);
    expect(screen.getByLabelText("Code")).toHaveValue("");
    expect(screen.getByLabelText("Kind")).toHaveValue("");
  });

  it("New User: Cancel goes back without a person", async () => {
    resetNav("/admin/users/new", "no_office=1&return=%2Fadmin%2Foffices%2Fnew%3Fdraft%3D1");
    routes(superAdmin(), { "GET /admin/users/lookup": json(404, { detail: "no such user" }) });
    renderWithClient(<NewUserForm noOffice returnTo="/admin/offices/new?draft=1" />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/offices/new?draft=1");
    // next to the one primary once the e-mail is checked
    await userEvent.type(screen.getByLabelText("E-mail"), "nirmal@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    const create = await screen.findByRole("button", { name: "Create User" });
    const actions = create.parentElement!;
    expect(within(actions).getByRole("button", { name: "Cancel" })).toHaveAttribute("data-variant", "secondary");
    expect(screen.getAllByRole("button", { name: "Cancel" })).toHaveLength(1);
    expect(document.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
  });

  it("New User without returnTo has no Cancel", async () => {
    resetNav("/admin/users/new");
    routes(superAdmin(), { "GET /admin/users/lookup": json(404, { detail: "no such user" }) });
    renderWithClient(<NewUserForm />);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    await userEvent.type(screen.getByLabelText("E-mail"), "nirmal@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    await screen.findByRole("button", { name: "Create User" });
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });
});

describe("the Reactivate dialog (decision 10)", () => {
  it("sends the same head body; ?reactivate=1 opens it and ?head= picks the person", async () => {
    resetNav("/admin/offices/AGRI", "reactivate=1&head=u-2");
    const office = {
      id: "o-9",
      code: "AGRI",
      name: "Agriculture",
      kind: "department",
      tier: "department",
      path: "GOA/AGRI",
      parent_code: "GOA",
      is_active: false,
      valid_from: "2026-01-01",
      notes: null,
      counts: { children: 0, users: 0, ownership: 0, custody: 0 },
    };
    const api = routes(superAdmin(), {
      "GET /admin/offices/AGRI": office,
      "GET /admin/offices/AGRI/admins": [],
      "GET /admin/users/u-2": RANI,
      "POST /admin/offices/AGRI/reactivate": { ...office, is_active: true },
    });
    renderWithClient(<OfficeDetailView code="AGRI" reactivate head="u-2" />);
    const dialog = await screen.findByRole("dialog", { name: "Reactivate" });
    await waitFor(() => expect(within(dialog).getByRole("combobox", { name: "Person" })).toHaveValue("Rani Bora"));
    expect(within(dialog).getByRole("link", { name: "Not in ASLMS Yet? Add a New User in Users" })).toHaveAttribute(
      "href",
      "/admin/users/new?no_office=1&return=%2Fadmin%2Foffices%2FAGRI%3Freactivate%3D1",
    );
    await waitFor(() => expect(within(within(dialog).getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(within(dialog).getByLabelText("Designation in This Department"), "d-sec");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reactivate" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({
      head: { user_id: "u-2", designation_id: "d-sec", designation: "Secretary" },
    });
    // office-head-picker-followups, decision 7: done, the address is cleaned
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/admin/offices/AGRI", { scroll: false }));
  });
});

describe("?reactivate=1 opens the dialog only when Reactivate is possible (office-head-picker-followups, decision 7)", () => {
  const OFFICE = {
    id: "o-9",
    code: "AGRI",
    name: "Agriculture",
    kind: "department",
    tier: "department",
    path: "GOA/AGRI",
    parent_code: "GOA",
    is_active: false,
    valid_from: "2026-01-01",
    notes: null,
    counts: { children: 0, users: 0, ownership: 0, custody: 0 },
  };

  function officeRoutes(me: ReturnType<typeof makeMe>, office: unknown, extra: Record<string, unknown> = {}) {
    return routes(me, { "GET /admin/offices/AGRI": office, "GET /admin/offices/AGRI/admins": [], ...extra });
  }

  async function refused() {
    await screen.findByRole("heading", { name: /Agriculture/ });
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/admin/offices/AGRI", { scroll: false }));
    expect(screen.queryByRole("dialog", { name: "Reactivate" })).toBeNull();
  }

  beforeEach(() => resetNav("/admin/offices/AGRI", "reactivate=1"));

  it("an active office: no dialog, and the already-active notice shows", async () => {
    officeRoutes(superAdmin(), { ...OFFICE, is_active: true });
    renderWithClient(<OfficeDetailView code="AGRI" reactivate />);
    await refused();
    expect(screen.getByText("This office is already active, so there is nothing to reactivate.")).toBeInTheDocument();
  });

  it("an inactive directorate: no dialog and no notice", async () => {
    officeRoutes(superAdmin(), { ...OFFICE, kind: "directorate", tier: "directorate" });
    renderWithClient(<OfficeDetailView code="AGRI" reactivate />);
    await refused();
    expect(screen.queryByText(/already active/)).toBeNull();
    // a directorate keeps the direct Reactivate
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
  });

  it("a caller without offices.manage: no dialog", async () => {
    officeRoutes(superAdmin(SUPER_FNS.filter((f) => f !== "offices.manage")), OFFICE);
    renderWithClient(<OfficeDetailView code="AGRI" reactivate />);
    await refused();
  });

  it("a department admin holding offices.manage: no dialog, and no Reactivate button on a Department-tier office", async () => {
    officeRoutes(deptAdmin(), OFFICE);
    renderWithClient(<OfficeDetailView code="AGRI" reactivate />);
    await refused();
    expect(screen.queryByRole("button", { name: "Reactivate" })).toBeNull();
    expect(screen.getByRole("link", { name: "New Office" })).toBeInTheDocument();
  });

  it("the Super Administrator on an inactive Department-tier office: the dialog opens; closing it cleans the address", async () => {
    resetNav("/admin/offices/AGRI", "reactivate=1&head=u-2");
    officeRoutes(superAdmin(), OFFICE, { "GET /admin/users/u-2": RANI });
    renderWithClient(<OfficeDetailView code="AGRI" reactivate head="u-2" />);
    const dialog = await screen.findByRole("dialog", { name: "Reactivate" });
    await waitFor(() => expect(within(dialog).getByRole("combobox", { name: "Person" })).toHaveValue("Rani Bora"));
    expect(nav.replace).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Reactivate" })).toBeNull());
    expect(nav.replace).toHaveBeenCalledWith("/admin/offices/AGRI", { scroll: false });
  });

  it("a deactivation after a refused ?reactivate=1 never opens the dialog", async () => {
    let active = true;
    officeRoutes(superAdmin(), () => ({ ...OFFICE, is_active: active }), {
      "POST /admin/offices/AGRI/deactivate": () => {
        active = false;
        return { ...OFFICE, is_active: false };
      },
    });
    renderWithClient(<OfficeDetailView code="AGRI" reactivate />);
    await refused();
    expect(screen.getByText(/already active/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await screen.findByRole("button", { name: "Reactivate" });
    expect(screen.queryByRole("dialog", { name: "Reactivate" })).toBeNull();
    expect(screen.queryByText(/already active/)).toBeNull();
  });
});

describe("the head-change request (decision 9)", () => {
  function requestOf(api: ReturnType<typeof routes>) {
    const call = api.calls.find((c) => c.method === "POST" && c.path === "/admin/tickets/head-change")!;
    return JSON.parse((call.body as FormData).get("request") as string);
  }

  it("names a member of the department by membership and anyone else by e-mail; greys elsewhere-offices and admins", async () => {
    resetNav("/admin/tickets/new", "department=EDU&operation=set");
    const api = routes(superAdmin(), { "POST /admin/tickets/head-change": json(201, { ref_no: "ASLMS/EDU/TKT/2026/000001" }) });
    renderWithClient(<NewTicketForm department="EDU" operation="set" />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Department" })).toHaveValue("Education"));
    expect(screen.getByLabelText("Change")).toHaveValue("set");
    expect(screen.queryByRole("button", { name: "Someone From Another Office" })).toBeNull();
    const box = screen.getByRole("combobox", { name: "Incoming Head" });
    await userEvent.type(box, "ra");
    const options = await within(await screen.findByRole("listbox", { name: "People" })).findAllByRole("option");
    expect(options).toHaveLength(5);
    const dse = options.find((o) => o.textContent?.includes("Rama Nath"))!;
    expect(dse).toHaveAttribute("aria-disabled", "true");
    expect(dse).toHaveTextContent("Works in EDU-DSE; a head sits at the department office");
    // the super admin may name the department's admin
    expect(options.find((o) => o.textContent?.includes("Rabin Admin"))).not.toHaveAttribute("aria-disabled");
    await userEvent.click(options.find((o) => o.textContent?.includes("Raju Deka"))!);
    await waitFor(() => expect(within(screen.getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText("Designation in This Department"), "d-sec");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(requestOf(api)).toMatchObject({
      operation: "set",
      department_code: "EDU",
      incoming: { membership_id: "m-3", designation: "Secretary", designation_id: "d-sec" },
    });
  });

  it("a person from another department goes by e-mail; a department admin sees Someone From Another Office", async () => {
    resetNav("/admin/tickets/new");
    const api = routes(deptAdmin(), {
      "POST /admin/tickets/head-change": json(202, { ref_no: "ASLMS/EDU/TKT/2026/000002" }),
      "GET /admin/users/lookup": { id: "u-8", full_name: "Moni Far", memberships: [] },
    });
    renderWithClient(<NewTicketForm />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Department" })).toBeDisabled());
    await pick("Incoming Head", "ra", "Ravi Das");
    expect(api.calls.some((c) => c.path.includes("include_ended"))).toBe(false);
    // the department admin of EDU is greyed for a requester who is not the Super Administrator
    await userEvent.clear(screen.getByRole("combobox", { name: "Incoming Head" }));
    await userEvent.type(screen.getByRole("combobox", { name: "Incoming Head" }), "rab");
    expect(await screen.findByText("Department Administrator — only the Super Administrator can name them head")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(within(screen.getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText("Designation in This Department"), "d-sec");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(requestOf(api).incoming).toEqual({ email: "ravi@example.org", designation: "Secretary", designation_id: "d-sec" });
    expect(requestOf(api).department_code).toBe("EDU");
    // Someone From Another Office: an exact e-mail checked with the lookup
    expect(screen.getByRole("button", { name: "Someone From Another Office" })).toBeInTheDocument();
  });

  it("a State-office users.view holder without cases.view_all: no include_ended, and Someone From Another Office", async () => {
    // office-head-picker-followups, decision 4: the server's rule (`access.user_scope_roots`), not the State office
    const fns: Permission[] = ["users.view", "users.create", "users.propose_head"];
    const reader = makeMe(fns, "state_oversight", {
      memberships: [
        {
          id: "m-st",
          office: { code: "GOA", name: "Government of Assam", kind: "state" },
          department_code: null,
          designation: null,
          role: "state_oversight",
          is_primary: true,
          is_active: true,
          functions: fns,
        },
      ],
    });
    resetNav("/admin/tickets/new", "department=EDU");
    const api = routes(reader);
    renderWithClient(<NewTicketForm department="EDU" />);
    await pick("Incoming Head", "ra", "Ravi Das");
    const search = api.calls.find((c) => c.path.startsWith("/admin/users?q=ra"))!;
    expect(search.path).not.toContain("include_ended");
    expect(screen.getByRole("button", { name: "Someone From Another Office" })).toBeInTheDocument();
  });

  it("the Super Administrator sends include_ended=true and sees no Someone From Another Office", async () => {
    resetNav("/admin/tickets/new", "department=EDU");
    const api = routes(superAdmin());
    renderWithClient(<NewTicketForm department="EDU" />);
    await pick("Incoming Head", "ra", "Ravi Das");
    expect(api.calls.some((c) => c.path === "/admin/users?q=ra&limit=20&include_ended=true")).toBe(true);
    expect(screen.queryByRole("button", { name: "Someone From Another Office" })).toBeNull();
  });

  it("Someone From Another Office checks the exact e-mail and sends it", async () => {
    resetNav("/admin/tickets/new");
    const api = routes(deptAdmin(), {
      "POST /admin/tickets/head-change": json(202, { ref_no: "ASLMS/EDU/TKT/2026/000003" }),
      "GET /admin/users/lookup": { id: "u-8", full_name: "Moni Far", memberships: [] },
    });
    renderWithClient(<NewTicketForm />);
    await userEvent.click(await screen.findByRole("button", { name: "Someone From Another Office" }));
    await userEvent.type(screen.getByLabelText("Someone From Another Office"), "moni@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    expect(await screen.findByText("Found: Moni Far.")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByLabelText("Designation in This Department")).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText("Designation in This Department"), "d-sec");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(requestOf(api).incoming).toEqual({ email: "moni@example.org", designation: "Secretary", designation_id: "d-sec" });
  });
});

describe("New User: No Office Yet (decision 15)", () => {
  async function unknownEmail() {
    await userEvent.type(screen.getByLabelText("E-mail"), "nirmal@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Check E-mail" }));
    await screen.findByRole("button", { name: "Create User" });
  }

  it("only the Super Administrator sees the tick", async () => {
    routes(deptAdmin(), { "GET /admin/users/lookup": json(404, { detail: "no such user" }) });
    renderWithClient(<NewUserForm />);
    await unknownEmail();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Office" })).toBeInTheDocument());
    expect(screen.queryByLabelText("No Office Yet")).toBeNull();
  });

  it("ticked (from ?no_office=1) hides the office fields, sends office_code and role null, and returns with ?head=", async () => {
    const api = routes(superAdmin(), {
      "GET /admin/users/lookup": json(404, { detail: "no such user" }),
      "POST /admin/users": json(201, user("u-new", "Nirmal New", "nirmal@example.org", [])),
    });
    renderWithClient(<NewUserForm noOffice returnTo="/admin/offices/AGRI?reactivate=1" />);
    await unknownEmail();
    const tick = await screen.findByLabelText("No Office Yet");
    expect(tick).toBeChecked();
    expect(screen.getByText(/For a person who will be named head of a department being created/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Office" })).toBeNull();
    expect(screen.queryByLabelText("User Type")).toBeNull();
    await userEvent.type(screen.getByLabelText("Full Name"), "Nirmal New");
    await userEvent.type(screen.getByLabelText("Temporary Password"), "given-by-root-1");
    await userEvent.click(screen.getByRole("button", { name: "Create User" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({
      email: "nirmal@example.org",
      full_name: "Nirmal New",
      password: "given-by-root-1",
      role: null,
      office_code: null,
      mobile: null,
    });
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/admin/offices/AGRI?reactivate=1&head=u-new"));
  });

  it("unticked shows the office fields again; a foreign return address goes to the dashboard", async () => {
    routes(superAdmin(), {
      "GET /admin/users/lookup": json(404, { detail: "no such user" }),
      "POST /admin/users": json(201, user("u-new", "Nirmal New", "nirmal@example.org", [])),
    });
    renderWithClient(<NewUserForm noOffice returnTo="https://elsewhere.example" />);
    await unknownEmail();
    await userEvent.click(await screen.findByLabelText("No Office Yet"));
    expect(screen.getByRole("combobox", { name: "Office" })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("No Office Yet"));
    await userEvent.type(screen.getByLabelText("Full Name"), "Nirmal New");
    await userEvent.type(screen.getByLabelText("Temporary Password"), "given-by-root-1");
    await userEvent.click(screen.getByRole("button", { name: "Create User" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/?head=u-new"));
  });
});

describe("Users and User Details (decision 17)", () => {
  it("the row shows No Office Yet, and More Filters' No Office Yet sends no_office=true", async () => {
    resetNav("/admin/users");
    const exited = user("u-6", "Ex Ited", "exited@example.org", [], { role: "dept_officer", office: RAVI.office });
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /reference/labels": labels(),
      "GET /admin/offices/choices": { purpose: "users", ...CHOICES },
      "GET /admin/users": () => json(200, [RANI, exited], { "x-total-count": "2" }),
    });
    renderWithClient(<UsersList params={{ no_office: "true" }} />);
    const table = await screen.findByRole("table", { name: "Users" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("No Office Yet")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("No Active Office")).toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/admin/users?") && c.path.includes("no_office=true"))).toBe(true));
    expect(screen.getByRole("button", { name: "More Filters (1)" })).toBeInTheDocument();
    expect(screen.getByLabelText("No Office Yet")).toBeChecked();
    await userEvent.click(screen.getByLabelText("No Office Yet"));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/users");
  });

  it("User Details says No Office Yet in the header and on the Offices tab, with Add Office", async () => {
    resetNav("/admin/users/u-2", "tab=offices");
    browserApi({
      "GET /me": superAdmin(),
      "GET /reference/labels": labels(),
      "GET /admin/offices/choices": { purpose: "users", ...CHOICES },
      "GET /admin/users": () => json(200, [RANI], { "x-total-count": "1" }),
      "GET /admin/users/u-2": RANI,
      "GET /admin/users/u-2/memberships": [],
    });
    renderWithClient(<UsersList params={{ tab: "offices" }} userId="u-2" />);
    const dialog = await screen.findByRole("dialog", { name: "Rani Bora" });
    expect(await within(dialog).findByText("No Office Yet")).toBeInTheDocument();
    expect(
      await within(dialog).findByText("No Office Yet. Add an office here, or name this person head when you create their department."),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Add Office" })).toBeInTheDocument();
  });
});

describe("the dashboard of a login with no office (decision 19)", () => {
  it("shows the No Office Yet card with a My Profile link", () => {
    renderWithClient(<NoDashboard me={makeMe([], "dept_officer", { memberships: [], user: { ...makeMe([]).user, role: null, office: null } })} />);
    expect(screen.getByText("No Office Yet")).toBeInTheDocument();
    expect(screen.getByText("Your login is ready. You will see cases once you are added to an office or named head of a department.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My Profile" })).toHaveAttribute("href", "/profile");
  });
});

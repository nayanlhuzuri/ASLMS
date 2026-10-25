import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ExitPreview, MembershipOut, Permission, UserOut } from "@/lib/api/types";
import { navigationModule, nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { membershipOrder, openUserDetails } from "./UserDetails";
import { UsersList } from "./Users";

const PRIMARY: MembershipOut = {
  id: "m-9",
  office: { code: "EDU-DSE", name: "Secondary Education", kind: "directorate" },
  department_code: "EDU",
  designation: "Section Officer",
  role: "directorate_user",
  is_primary: true,
  is_active: true,
  valid_from: "2026-01-05",
};
const SECOND: MembershipOut = {
  id: "m-10",
  office: { code: "EDU", name: "Education", kind: "department" },
  department_code: "EDU",
  designation: "Under Secretary",
  role: "dept_officer",
  is_primary: false,
  is_active: true,
  valid_from: "2026-03-01",
};
const ENDED: MembershipOut = {
  id: "m-8",
  office: { code: "HEALTH", name: "Health", kind: "department" },
  department_code: "HEALTH",
  designation: "Section Officer",
  role: "dept_officer",
  is_primary: false,
  is_active: false,
  valid_from: "2025-01-01",
  valid_to: "2025-12-31",
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
  last_login_at: "2026-10-20T04:30:00Z",
  created_at: "2026-01-05T00:00:00Z",
  memberships: [PRIMARY, SECOND],
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
];

const PERMISSIONS = [
  { code: "cases.view_scope", module: "cases", label: "See Cases", description: "Read the cases of the office.", is_active: true, group: "cases", group_label: "Cases", sort_in_group: 1 },
  { code: "notes.add", module: "notes", label: "Add Notes", description: null, is_active: true, group: "cases", group_label: "Cases", sort_in_group: 2 },
  { code: "users.view", module: "users", label: "See Users", description: null, is_active: true, group: "people", group_label: "People and Access", sort_in_group: 1 },
  { code: "custody.move", module: "custody", label: "Send Cases", description: null, is_active: true, group: "work", group_label: "Case Work", sort_in_group: 1 },
];

function routes(me: ReturnType<typeof makeMe>, extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": me,
    "GET /reference/labels": labels(["dept_officer", "directorate_user", "standing_counsel", "referral_reviewer"]),
    "GET /admin/users": () => json(200, [USER], { "x-total-count": "1" }),
    "GET /admin/users/u-9": USER,
    "GET /admin/users/u-9/memberships": [ENDED, SECOND, PRIMARY],
    "GET /admin/designations": [],
    "GET /admin/permissions": PERMISSIONS,
    "GET /admin/offices/choices": {
      purpose: "users",
      items: [
        { code: "EDU", name: "Education", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
        { code: "EDU-DSE", name: "Secondary Education", kind: "directorate", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: ["Government of Assam", "Education"], is_active: true },
      ],
    },
    "GET /admin/users/u-9/memberships/m-9/permissions": {
      membership_id: "m-9",
      role: "directorate_user",
      type_functions: ["cases.view_scope", "notes.add"],
      overrides: [
        { permission: "users.view", effect: "grant", is_active: true, reason: "covers the cell", valid_from: "2026-01-05", valid_to: null },
        { permission: "notes.add", effect: "deny", is_active: true, reason: null, valid_from: "2026-01-05", valid_to: null },
      ],
      effective: ["cases.view_scope", "users.view"],
    },
    ...extra,
  });
}

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

async function openModal(params: Record<string, string> = {}) {
  renderWithClient(<UsersList params={params} userId="u-9" />);
  return screen.findByRole("dialog", { name: "Ravi Das" });
}

beforeEach(() => resetNav("/admin/users/u-9"));

describe("the address (design portal-ui-polish-2, decision 31)", () => {
  it("/admin/users/<id> opens the modal over the list, the list's filters kept", async () => {
    const api = routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal({ status: "active" });
    // the list renders behind
    expect(await screen.findByRole("table", { name: "Users", hidden: true })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/admin/users?") && c.path.includes("status=active"))).toBe(true);
    expect(within(dialog).getByRole("navigation", { name: "User details" })).toBeInTheDocument();
  });

  it("the old ?user=<id> address redirects with the query string kept; ?user=new stays", async () => {
    const { default: Page } = await import("@/app/(portal)/admin/users/page");
    const redirect = navigationModule.redirect;
    redirect.mockReset();
    await Page({ searchParams: Promise.resolve({ user: "u-9", status: "active" }) });
    expect(redirect).toHaveBeenCalledWith("/admin/users/u-9?status=active");
    redirect.mockReset();
    await Page({ searchParams: Promise.resolve({ user: "new" }) });
    expect(redirect).not.toHaveBeenCalled();
  });

  it("Escape closes to the list's address when the modal was not opened in the portal", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    await openModal({ status: "active", tab: "offices" });
    await userEvent.keyboard("{Escape}");
    expect(nav.replace).toHaveBeenCalledWith("/admin/users?status=active");
    expect(nav.back).not.toHaveBeenCalled();
  });

  it("opened from a row, the overlay and Close go back", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    openUserDetails(nav, "u-9", { status: "active" });
    expect(nav.push).toHaveBeenCalledWith("/admin/users/u-9?status=active");
    const dialog = await openModal({ status: "active" });
    await waitFor(() => expect((window.history.state as Record<string, unknown>)?.__aslmsOverlay).toBe("user-details=u-9"));
    fireEvent.click(dialog.parentElement!);
    expect(nav.back).toHaveBeenCalledTimes(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(nav.back).toHaveBeenCalledTimes(2);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("the tab lives in ?tab= without a new history entry", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal({ tab: "functions" });
    const tabs = within(dialog).getByRole("navigation", { name: "User details" });
    expect(within(tabs).getByRole("link", { name: "Functions" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(within(tabs).getByRole("link", { name: /Offices/ }));
    expect(window.location.search).toBe("?tab=offices");
    expect(nav.push).not.toHaveBeenCalled();
    expect(within(tabs).getByRole("link", { name: /Offices/ })).toHaveAttribute("aria-current", "page");
    expect(await within(dialog).findByRole("list", { name: "Offices" })).toBeInTheDocument();
  });
});

describe("the header and its menus (decision 32)", () => {
  it("shows the facts; each action only with its function; no Sign Out Everywhere", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal();
    expect(await within(dialog).findByText("Section Officer · Secondary Education")).toBeInTheDocument();
    expect(within(dialog).getAllByText("ravi@example.org").length).toBeGreaterThan(0);
    expect(within(dialog).getAllByText("9864012345").length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/^Last Sign-in: /)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Edit Profile" })).toHaveAttribute("data-variant", "secondary");
    await userEvent.click(within(dialog).getByRole("button", { name: "More" }));
    const items = within(screen.getByRole("menu", { name: "More" })).getAllByRole("menuitem").map((i) => i.textContent);
    expect(items).toEqual(["Reset Password", "Turn Sign-in Off"]);
    expect(screen.queryByText(/Sign Out Everywhere/)).toBeNull();
  });

  it("a reader without the functions gets no Edit Profile and no More", async () => {
    routes(makeMe(["users.view"], "state_oversight"));
    const dialog = await openModal();
    await within(dialog).findByText("Section Officer · Secondary Education");
    expect(within(dialog).queryByRole("button", { name: "Edit Profile" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "More" })).toBeNull();
  });

  it("Turn Sign-in Off posts disable; Edit Profile sends only changed fields", async () => {
    const api = routes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "POST /admin/users/u-9/disable": { ...USER, is_active: false },
      "PATCH /admin/users/u-9": { ...USER, mobile: "9000000000" },
    });
    const dialog = await openModal();
    await userEvent.click(await within(dialog).findByRole("button", { name: "More" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Turn Sign-in Off" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/admin/users/u-9/disable")).toBe(true));
    await userEvent.click(within(dialog).getByRole("button", { name: "Edit Profile" }));
    const edit = await screen.findByRole("dialog", { name: "Edit Profile" });
    await userEvent.clear(within(edit).getByLabelText("Mobile"));
    await userEvent.type(within(edit).getByLabelText("Mobile"), "9000000000");
    await userEvent.click(within(edit).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ mobile: "9000000000" });
  });
});

describe("Overview (decision 33)", () => {
  it("shows the person and the primary office with the sign-in notice", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal();
    const person = await within(dialog).findByRole("region", { name: "Person" });
    expect(within(person).getByText("Full Name")).toBeInTheDocument();
    const office = within(dialog).getByRole("region", { name: "Primary Office" });
    await waitFor(() => expect(within(office).getByText("2 active")).toBeInTheDocument());
    expect(within(office).getByText("Directorate user")).toBeInTheDocument();
    expect(within(dialog).getByText(/Sign-in uses a 6-digit code/)).toBeInTheDocument();
  });
});

describe("Offices (decision 34)", () => {
  it("orders the cards active and primary first, with the badges, the path and the footer lines", async () => {
    expect(membershipOrder([ENDED, SECOND, PRIMARY]).map((m) => m.id)).toEqual(["m-9", "m-10", "m-8"]);
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal({ tab: "offices" });
    const list = await within(dialog).findByRole("list", { name: "Offices" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards.map((c) => c.getAttribute("data-membership"))).toEqual(["m-9", "m-10", "m-8"]);
    expect(within(cards[0]!).getByText("Primary")).toBeInTheDocument();
    expect(within(cards[0]!).getByText("Active")).toBeInTheDocument();
    expect(within(cards[2]!).getByText("Ended")).toBeInTheDocument();
    expect(await within(cards[0]!).findByText("Government of Assam › Education")).toBeInTheDocument();
    expect(within(cards[0]!).getByText("Shown first wherever this person appears.")).toBeInTheDocument();
    expect(within(cards[1]!).getByText("An additional office.")).toBeInTheDocument();
    expect(within(cards[2]!).getByText("Kept in the history.")).toBeInTheDocument();
    // the tab's count is the active offices
    expect(within(dialog).getByRole("link", { name: /Offices/ })).toHaveTextContent("2");
  });

  it("the Actions menu offers each item with its function; End Membership is red, last and opens the exit dialog", async () => {
    const preview: ExitPreview = {
      counts: { allotments: 1, files: 0, drafts: 0, open_alerts: 0 },
      items_fingerprint: "fp-1",
      primary_after: null,
      items: [
        { key: "allotment:1", kind: "allotment", case: { ref_no: "EDU/2026/0001", case_no: "WP(C)/1/2026", cnr: null, court: null, owning_department: "EDU", visible: true }, open_alerts: 0 },
      ],
      targets: [{ membership: "m-20", name: "Mira Bora", designation: "Deputy Secretary", office_code: "EDU", role: "dept_officer" }],
    };
    const api = routes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "GET /admin/users/u-9/memberships/m-10/exit-preview": preview,
      "POST /admin/users/u-9/memberships/m-10/end": { membership: { ...SECOND, is_active: false }, reassigned: [], counts: {} },
    });
    const dialog = await openModal({ tab: "offices" });
    const cards = within(await within(dialog).findByRole("list", { name: "Offices" })).getAllByRole("listitem");
    await userEvent.click(within(cards[1]!).getByRole("button", { name: "Actions for Education" }));
    const menu = screen.getByRole("menu", { name: "Actions for Education" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "Change",
      "Make Primary",
      "Functions and Overrides",
      "Government Orders",
      "End Membership",
    ]);
    expect(within(menu).getByRole("separator")).toBeInTheDocument();
    const end = within(menu).getByRole("menuitem", { name: "End Membership" });
    expect(end.closest("li")!.className).toMatch(/menuDanger/);
    await userEvent.click(end);
    const exit = await screen.findByRole("dialog", { name: "End Membership: Education" });
    expect(await within(exit).findByText("WP(C)/1/2026")).toBeInTheDocument();
    const submit = within(exit).getByRole("button", { name: "End Membership" });
    expect(submit).toHaveAttribute("data-variant", "danger");
    await userEvent.type(within(exit).getByLabelText("Reason for Ending"), "transferred out");
    expect(submit).toBeDisabled();
    await userEvent.selectOptions(within(exit).getByLabelText("Successor EDU/2026/0001"), "m-20");
    await userEvent.click(submit);
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path.endsWith("/end"))).toBe(true));
    expect(api.calls.find((c) => c.path.endsWith("/end"))!.body).toEqual({
      reason: "transferred out",
      items_fingerprint: "fp-1",
      assignments: [{ key: "allotment:1", to_membership: "m-20" }],
    });
  });

  it("the primary card has no Make Primary; an ended card has Reactivate; a reader sees neither", async () => {
    const api = routes(makeMe(DEPT_ADMIN, "dept_admin"), { "POST /admin/users/u-9/memberships/m-8/reactivate": { ...ENDED, is_active: true } });
    const dialog = await openModal({ tab: "offices" });
    const cards = within(await within(dialog).findByRole("list", { name: "Offices" })).getAllByRole("listitem");
    await userEvent.click(within(cards[0]!).getByRole("button", { name: "Actions for Secondary Education" }));
    expect(screen.queryByRole("menuitem", { name: "Make Primary" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(within(cards[2]!).queryByRole("button", { name: /Actions/ })).toBeNull();
    await userEvent.click(within(cards[2]!).getByRole("button", { name: "Reactivate" }));
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith("/m-8/reactivate"))).toBe(true));
  });

  it("a reader with users.view only gets Functions and Overrides and no Add Office", async () => {
    routes(makeMe(["users.view"], "state_oversight"));
    const dialog = await openModal({ tab: "offices" });
    const cards = within(await within(dialog).findByRole("list", { name: "Offices" })).getAllByRole("listitem");
    await userEvent.click(within(cards[0]!).getByRole("button", { name: /Actions/ }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Functions and Overrides"]);
    expect(within(cards[2]!).queryByRole("button", { name: "Reactivate" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Add Office" })).toBeNull();
  });

  it("Change offers only the assignable types; Add Office uses the Office Picker (purpose membership)", async () => {
    const api = routes(makeMe(DEPT_ADMIN, "dept_admin"), {
      "POST /admin/users/u-9/memberships": { ...SECOND, id: "m-30" },
    });
    const dialog = await openModal({ tab: "offices" });
    const cards = within(await within(dialog).findByRole("list", { name: "Offices" })).getAllByRole("listitem");
    await userEvent.click(within(cards[0]!).getByRole("button", { name: /Actions/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Change" }));
    const change = await screen.findByRole("dialog", { name: "Change: Secondary Education" });
    const options = within(within(change).getByLabelText("User Type")).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options.sort()).toEqual(["dept_officer", "directorate_user", "referral_reviewer", "standing_counsel"]);
    await userEvent.click(within(change).getByRole("button", { name: "Close" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Add Office" }));
    const add = await screen.findByRole("dialog", { name: "Add Office" });
    await userEvent.click(within(add).getByRole("combobox", { name: "Office" }));
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Education"));
    await userEvent.selectOptions(within(add).getByLabelText("User Type"), "dept_officer");
    await userEvent.click(within(add).getByRole("button", { name: "Add Office" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/admin/users/u-9/memberships")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ office: "EDU", designation: null, role: "dept_officer" });
    expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=membership")).toBe(true);
  });
});

describe("Functions (decision 35)", () => {
  it("lists the held functions by group with the Given and Taken marks and the line", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal({ tab: "functions" });
    expect(await within(dialog).findByText("Holds 2 functions here: those of Directorate user, 1 given, 1 taken.")).toBeInTheDocument();
    const cases = within(dialog).getByRole("heading", { name: "Cases" }).closest("section")!;
    expect(within(cases).getByText("See Cases")).toBeInTheDocument();
    const taken = within(cases).getByText("Add Notes");
    expect(taken.className).toMatch(/fnTaken/);
    expect(within(cases).getByText("Taken From This Person")).toBeInTheDocument();
    const people = within(dialog).getByRole("heading", { name: "People and Access" }).closest("section")!;
    expect(within(people).getByText("Given to This Person")).toBeInTheDocument();
    // a function neither held nor taken is not listed
    expect(within(dialog).queryByText("Send Cases")).toBeNull();
    const select = within(dialog).getByLabelText("Office");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Secondary Education · Directorate user",
      "Education · Dept officer",
    ]);
    expect(within(dialog).getByRole("button", { name: "Change Exceptions" })).toBeInTheDocument();
  });

  it("Change Exceptions opens the switches in a side panel, only with users.grant", async () => {
    routes(makeMe(DEPT_ADMIN, "dept_admin"));
    const dialog = await openModal({ tab: "functions" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Change Exceptions" }));
    const panel = await screen.findByRole("dialog", { name: "Change Exceptions: Secondary Education" });
    expect(await within(panel).findByRole("table", { name: "Functions" })).toBeInTheDocument();
  });

  it("no Change Exceptions without users.grant; a login with no active office holds nothing", async () => {
    routes(makeMe(["users.view"], "state_oversight"), { "GET /admin/users/u-9/memberships": [ENDED] });
    const dialog = await openModal({ tab: "functions" });
    expect(await within(dialog).findByText("This login has no active office, so it holds no functions.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Change Exceptions" })).toBeNull();
  });
});

describe("Activity (decision 36)", () => {
  it("shows for an audit reader, calling GET /audit?user=<id>&limit=20, with the link to the Audit Log", async () => {
    const api = routes(superAdmin([...DEPT_ADMIN, "audit.view", "cases.view_all"]), {
      "GET /audit": {
        items: [
          {
            id: "a-1",
            at: "2026-10-24T10:42:00+05:30",
            action: "ownership.claim",
            entity_type: "case",
            entity_id: null,
            case: { id: "c-1", ref_no: "ASLMS/EDU/CASE/2026/000001", cnr: null, case_no_text: "WP(C)/2987/2026" },
            actor: { user_id: "u-9", name: "Ravi Das", designation: null, office_code: "EDU" },
            ip: null,
            user_agent: null,
          },
        ],
        next_cursor: null,
      },
    });
    const dialog = await openModal();
    await userEvent.click(await within(dialog).findByRole("link", { name: "Activity" }));
    expect(await within(dialog).findByText("Case WP(C)/2987/2026")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/audit?user=u-9&limit=20")).toBe(true);
    expect(within(dialog).getByRole("link", { name: "Open in Audit Log" })).toHaveAttribute("href", "/audit?user=u-9");
  });

  it("is not shown without readsAudit, and no audit call is made", async () => {
    const api = routes(makeMe([...DEPT_ADMIN, "audit.view"], "dept_admin"));
    const dialog = await openModal({ tab: "activity" });
    await within(dialog).findByRole("region", { name: "Person" });
    expect(within(dialog).queryByRole("link", { name: "Activity" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/audit"))).toBe(false);
  });
});

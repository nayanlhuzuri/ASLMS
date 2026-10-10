import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ExitPreview, MembershipOut, Permission, TicketDetail, UserOut } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { AccessMatrix } from "./Access";
import { OfficeDetailView } from "./Offices";
import { TicketView } from "./Tickets";
import { UserDetail } from "./UserDetail";
import { NewUserForm } from "./Users";

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
    for (const name of ["Edit", "Disable login", "Set a temporary password", "End membership", "Change", "Add a membership", "Government orders"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByRole("button", { name: "Functions and overrides" })).toBeInTheDocument();
  });

  it("shows each action with its function", async () => {
    userRoutes(makeMe(DEPT_ADMIN, "dept_admin"));
    renderWithClient(<UserDetail id="u-9" />);
    await screen.findByRole("heading", { name: "Ravi Das" });
    for (const name of ["Edit", "Disable login", "Set a temporary password", "End membership", "Change", "Add a membership", "Government orders"]) {
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
    await userEvent.click(await screen.findByRole("button", { name: "End membership" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("WP(C)/1/2026")).toBeInTheDocument();
    expect(within(dialog).getByText("WA/2/2026")).toBeInTheDocument();
    const submit = within(dialog).getByRole("button", { name: "End membership" });
    await userEvent.type(within(dialog).getByLabelText("Reason for ending"), "transferred out");
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
    const options = within(within(dialog).getByLabelText("User type")).getAllByRole("option").map((o) => o.getAttribute("value"));
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
    await userEvent.click(screen.getByRole("button", { name: "Check e-mail" }));
    expect(await screen.findByText("Mira Bora already has a login.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create user" })).toBeNull();
    await userEvent.type(screen.getByLabelText("Office code"), "EDU");
    await userEvent.selectOptions(screen.getByLabelText("User type"), "dept_officer");
    await userEvent.click(screen.getByRole("button", { name: "Add a membership to this person" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Check e-mail" }));
    expect(await screen.findByRole("button", { name: "Create user" })).toBeInTheDocument();
    const values = within(screen.getByLabelText("User type"))
      .getAllByRole("option")
      .map((o) => o.getAttribute("value"))
      .filter(Boolean);
    expect(values).toEqual(["dept_officer", "directorate_user"]);
  });
});

describe("type matrix", () => {
  const matrix = { super_admin: { "users.view": true }, dept_admin: { "users.view": true }, dept_officer: { "users.view": false } };
  const perms = [{ code: "users.view", module: "users", label: "View users", description: null, is_active: true }];

  it("is read-only without access.manage_types", async () => {
    browserApi({
      "GET /me": makeMe(["users.view"], "dept_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/access/types": matrix,
      "GET /admin/permissions": perms,
    });
    renderWithClient(<AccessMatrix />);
    expect(await screen.findByText("You can read the matrix; only the super admin changes it.")).toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByRole("img", { name: "View users for Dept officer: not enabled" })).toBeInTheDocument();
  });

  it("can be switched with access.manage_types", async () => {
    const api = browserApi({
      "GET /me": makeMe(["users.view", "access.manage_types"], "super_admin"),
      "GET /reference/labels": labels(),
      "GET /admin/access/types": matrix,
      "GET /admin/permissions": perms,
      "PUT /admin/access/types/dept_officer/users.view": { "users.view": true },
    });
    renderWithClient(<AccessMatrix />);
    const box = await screen.findByRole("checkbox", { name: "View users for Dept officer" });
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({ enabled: true });
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

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import type { AuditRow, Me, Permission, Role } from "@/lib/api/types";
import { addDays, istDay } from "@/lib/format";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, labels, makeMe, primaryActions, renderWithClient, type BrowserCall } from "@/test/render";

import { AuditEntry } from "./AuditEntry";
import { BeforeAfter } from "./BeforeAfter";
import { AuditSearch } from "./AuditSearch";

function meWith(role: Role, functions: Permission[], departmentCode: string | null = null): Me {
  return makeMe(functions, role, {
    memberships: [
      {
        id: "m-1",
        office: { code: departmentCode ?? "GOA", name: departmentCode ?? "Government of Assam", kind: "department" },
        department_code: departmentCode,
        designation: null,
        role,
        is_primary: true,
        is_active: true,
        functions,
      },
    ],
  });
}

const SUPER = meWith("super_admin", ["audit.view", "cases.view_all", "cases.view_scope", "users.view"]);
const AUDITOR = meWith("auditor", ["audit.view", "cases.view_all", "cases.view_scope"]);
const DEPT_AUDIT = meWith("dept_admin", ["audit.view", "cases.view_scope", "users.view"], "EDU");

function row(id: string, extra: Partial<AuditRow> = {}): AuditRow {
  return {
    id,
    at: "2026-10-14T09:04:07Z",
    action: "ownership.claim",
    entity_type: "case_ownership",
    entity_id: "0192a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
    case: { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", cnr: "ASHC010000012026", case_no_text: "WP(C)/1/2026" },
    actor: { user_id: "u-7", name: "Anita Sharma", designation: "Under Secretary", office_code: "EDU" },
    ip: "10.0.0.5",
    user_agent: "Mozilla/5.0",
    before: null,
    after: { department: "EDU" },
    ...extra,
  };
}

const ACTIONS = { actions: ["custody.sent", "ownership.claim", "auth.login", "custody.recalled"] };
const DEPARTMENTS = {
  items: [],
  total: 0,
  units: [],
  departments: [
    { code: "EDU", name: "Education" },
    { code: "FIN", name: "Finance" },
  ],
};
const EDU_PEOPLE = {
  items: [],
  total: 0,
  departments: [],
  units: [
    { code: "EDU-DSE", name: "Secondary Education" },
    { code: "EDU-ACC", name: "Accounts" },
  ],
};

const CHOICES = {
  purpose: "audit",
  items: [
    { code: "GOA", name: "Government of Assam", kind: "state", tier: "state", depth: 0, parent_code: null, ancestors: [], is_active: true },
    { code: "EDU", name: "Education", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
    { code: "EDU-ACC", name: "Accounts", kind: "unit", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: ["Government of Assam", "Education"], is_active: true },
    { code: "OLD-OFFICE", name: "Old Office", kind: "unit", tier: "directorate", depth: 2, parent_code: "EDU", ancestors: ["Government of Assam", "Education"], is_active: false },
  ],
};

function recipients(call: BrowserCall) {
  return call.url.includes("department=EDU") ? EDU_PEOPLE : DEPARTMENTS;
}

function auditCalls(api: { calls: BrowserCall[] }) {
  return api.calls.filter((c) => c.path.split("?")[0] === "/audit");
}

function queryOf(call: BrowserCall): Record<string, string> {
  return Object.fromEntries(new URL(call.url, "http://x").searchParams.entries());
}

function routes(page: unknown = { items: [row("r-1")], next_cursor: null }, extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": SUPER,
    "GET /audit": page,
    "GET /audit/actions": ACTIONS,
    "GET /custody/recipients": recipients,
    "GET /admin/offices/choices": CHOICES,
    ...extra,
  });
}

beforeEach(() => {
  resetNav("/audit");
  try {
    window.sessionStorage.clear();
  } catch {
    // no storage
  }
});

describe("navigation", () => {
  it("the Audit log entry shows for the super admin and the Auditor only", () => {
    for (const [me, shown] of [
      [SUPER, true],
      [AUDITOR, true],
      [DEPT_AUDIT, false],
      [meWith("dept_officer", ["cases.view_scope"], "EDU"), false],
    ] as const) {
      browserApi({ "GET /reference/labels": labels() });
      const { unmount } = renderWithClient(<Sidebar me={me} />);
      const sidebar = screen.getByRole("navigation", { name: "Main Navigation" });
      const link = within(sidebar).queryByRole("treeitem", { name: "Audit Log" });
      if (shown) {
        expect(link).toHaveAttribute("href", "/audit");
        const names = within(sidebar)
          .getAllByRole("treeitem")
          .map((a) => a.textContent);
        expect(names.indexOf("Data Collection") === -1 || names.indexOf("Data Collection") > names.indexOf("Audit Log")).toBe(true);
      } else {
        expect(link).toBeNull();
      }
      unmount();
    }
  });
});

describe("the search", () => {
  it("runs on open with the URL's filters and limit=50", async () => {
    const api = routes();
    renderWithClient(<AuditSearch params={{ case: "GHC-1", action: "custody.", offset: "10", user: "" }} />);
    await screen.findByRole("table", { name: "Audit Log Entries" });
    const calls = auditCalls(api);
    expect(calls).toHaveLength(1);
    expect(queryOf(calls[0]!)).toEqual({ case: "GHC-1", action: "custody.", limit: "50" });
  });

  it("with no filter lists the newest entries", async () => {
    const api = routes({ items: [row("r-1"), row("r-2", { action: "custody.sent" })], next_cursor: null });
    renderWithClient(<AuditSearch params={{}} />);
    const table = await screen.findByRole("table", { name: "Audit Log Entries" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(queryOf(auditCalls(api)[0]!)).toEqual({ limit: "50" });
  });

  it("Search writes the filters to the URL; Clear goes to /audit", async () => {
    routes();
    renderWithClient(<AuditSearch params={{}} />);
    await screen.findByRole("table");
    await userEvent.type(screen.getByLabelText("Person"), "ravi@example.org");
    await userEvent.type(screen.getByLabelText("Case"), "ASHC010000012026");
    // design portal-ui-polish-2, decision 23: the period hero's quick choice
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenCalledTimes(1);
    const url = new URL(nav.push.mock.calls[0]![0] as string, "http://x");
    expect(url.pathname).toBe("/audit");
    const q = Object.fromEntries(url.searchParams.entries());
    expect(q.user).toBe("ravi@example.org");
    expect(q.case).toBe("ASHC010000012026");
    expect(q.from).toBe(q.to);
    expect(Object.keys(q).sort()).toEqual(["case", "from", "to", "user"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit");
  });

  it("More appends the next page by cursor and disappears without next_cursor", async () => {
    const api = routes((call: BrowserCall) =>
      call.url.includes("cursor=c1")
        ? { items: [row("r-3", { action: "custody.sent" })], next_cursor: null }
        : { items: [row("r-1"), row("r-2")], next_cursor: "c1" },
    );
    renderWithClient(<AuditSearch params={{ office: "EDU" }} />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await waitFor(() => expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(4));
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
    const second = auditCalls(api)[1]!;
    expect(queryOf(second)).toEqual({ office: "EDU", limit: "50", cursor: "c1" });
  });

  it("rows render, and the name, office and action links narrow the search", async () => {
    routes({
      items: [
        row("r-1"),
        row("r-2", { actor: { user_id: null, name: null, designation: null, office_code: null }, case: null }),
      ],
      next_cursor: null,
    });
    renderWithClient(<AuditSearch params={{ from: "2026-10-01" }} />);
    const table = await screen.findByRole("table");
    const [, first, second] = within(table).getAllByRole("row");
    expect(within(first!).getByText("14 Oct 2026, 14:34:07")).toBeInTheDocument();
    expect(within(first!).getByRole("link", { name: "ownership.claim" })).toHaveAttribute(
      "href",
      "/audit?from=2026-10-01&action=ownership.claim",
    );
    expect(within(first!).getByRole("link", { name: "Anita Sharma" })).toHaveAttribute("href", "/audit?from=2026-10-01&user=u-7");
    expect(within(first!).getByText(/Under Secretary/)).toBeInTheDocument();
    expect(within(first!).getByRole("link", { name: "EDU" })).toHaveAttribute("href", "/audit?from=2026-10-01&office=EDU");
    expect(within(first!).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute(
      "href",
      "/cases/ASLMS-GHC-CASE-2026-000001",
    );
    expect(within(first!).getByRole("link", { name: /View the entry/ })).toHaveAttribute("href", "/audit/r-1");
    expect(within(second!).getByText("System")).toBeInTheDocument();
    expect(within(second!).getByText("—")).toBeInTheDocument();
    // IP address and browser are on the entry page only
    expect(screen.queryByText("10.0.0.5")).toBeNull();
  });

  it("the action list is grouped with All … actions entries", async () => {
    routes();
    renderWithClient(<AuditSearch params={{}} />);
    await screen.findByRole("option", { name: "All Custody Actions" });
    const select = screen.getByLabelText("Action");
    expect(within(select).getByRole("option", { name: "Any Action" })).toHaveValue("");
    expect(within(select).getByRole("option", { name: "All Custody Actions" })).toHaveValue("custody.");
    expect(within(select).getByRole("option", { name: "All Sign-in and Password Actions" })).toHaveValue("auth.");
    expect(within(select).getByRole("option", { name: "custody.recalled" })).toBeInTheDocument();
    const groups = within(select).getAllByRole("group").map((g) => g.getAttribute("label"));
    expect(groups).toEqual(["Custody", "Ownership", "Sign-in and Password"]);
    await userEvent.selectOptions(select, "custody.");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit?action=custody.");
  });

  it("the Office Picker (purpose audit) lists inactive offices and sends office_subtree=false when Include Sub-offices is cleared", async () => {
    const api = routes();
    renderWithClient(<AuditSearch params={{}} />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.click(box);
    const list = await screen.findByRole("listbox");
    expect(within(within(list).getByText("Old Office").closest("li")!).getByText("Inactive")).toBeInTheDocument();
    await userEvent.click(within(list).getByText("Education"));
    expect(screen.getByText("+ sub")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit?office=EDU");
    await userEvent.click(screen.getByLabelText("Include Sub-offices"));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit?office=EDU&office_subtree=false");
    expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=audit")).toBe(true);
  });

  it("office_subtree from the address is sent to the API and unticks the box", async () => {
    const api = routes();
    renderWithClient(<AuditSearch params={{ office: "EDU", office_subtree: "false" }} />);
    await waitFor(() => expect(auditCalls(api).length).toBeGreaterThan(0));
    expect(queryOf(auditCalls(api)[0]!)).toMatchObject({ office: "EDU", office_subtree: "false" });
    expect(screen.getByLabelText("Include Sub-offices")).not.toBeChecked();
  });

  it("the unit select still appears after a department is chosen and sends the unit's code", async () => {
    routes();
    renderWithClient(<AuditSearch params={{}} />);
    expect(screen.queryByLabelText("Unit")).toBeNull();
    await userEvent.click(await screen.findByRole("combobox", { name: "Office" }));
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Education"));
    // Layout B: the unit is under More Filters (design portal-ui-polish-2, decision 23)
    await userEvent.click(screen.getByRole("button", { name: /^More Filters/ }));
    await screen.findByRole("option", { name: "Accounts (EDU-ACC)" });
    await userEvent.selectOptions(screen.getByLabelText("Unit"), "EDU-ACC");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit?office=EDU-ACC");
  });

  it("an inactive office from the address is shown by its name", async () => {
    routes();
    renderWithClient(<AuditSearch params={{ office: "OLD-OFFICE" }} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Office" })).toHaveValue("Old Office"));
  });

  it.each([
    ["unknown_user", { user: "nobody@example.org" }, "Person", "No such user."],
    ["unknown_user", { about_user: "nobody@example.org" }, "About the User", "No such user."],
    ["not_found", { case: "GHC-MADE-UP" }, "Case", "No case with this reference"],
    ["bad_office", { office: "NOPE" }, "Office", "No office with this code."],
    ["bad_period", { from: "2026-10-01", to: "2026-10-02" }, "To", "from must not be after to"],
    ["bad_period", { from: addDays(istDay(), -6), to: istDay() }, "To", "from must not be after to"],
  ] as const)("API refusal %s shows under its field and no list", async (code, params, label, text) => {
    const status = code === "not_found" ? 404 : 400;
    routes(json(status, { detail: { code, message: code === "bad_period" ? "from must not be after to" : "refused" } }));
    renderWithClient(<AuditSearch params={params} />);
    const field = await screen.findByLabelText(label);
    await waitFor(() => expect(field).toHaveAccessibleDescription(expect.stringContaining(text)));
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("unknown_user shows under both people fields when both were sent", async () => {
    routes(json(400, { detail: { code: "unknown_user", message: "no such user" } }));
    renderWithClient(<AuditSearch params={{ user: "a@example.org", about_user: "b@example.org" }} />);
    await waitFor(() => expect(screen.getAllByText("No such user.")).toHaveLength(2));
  });

  it("a 503 shows the narrow-the-search message with Try again", async () => {
    routes(json(503, { detail: { code: "search_timeout", message: "the search took too long; narrow the search" } }));
    renderWithClient(<AuditSearch params={{ actor: "Sharma" }} />);
    expect(await screen.findByText("The search took too long; narrow the search.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a 403 shows the readers sentence and no form, and requests nothing more", async () => {
    const api = routes(json(403, { detail: { code: "audit_scope", message: "State-wide only" } }));
    renderWithClient(<AuditSearch params={{}} />);
    expect(await screen.findByText("The audit log is read only by the Super Administrator and the Auditor.")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Audit Log Filters" })).toBeNull();
    expect(api.calls.filter((c) => c.path.startsWith("/audit/actions"))).toHaveLength(0);
    expect(auditCalls(api)).toHaveLength(1);
  });

  it("browser checks stop the request", async () => {
    const api = routes();
    renderWithClient(<AuditSearch params={{}} />);
    await screen.findByRole("table");
    const before = api.calls.length;
    await userEvent.type(screen.getByLabelText("Name Contains"), "S");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Give 2 to 100 characters.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Name Contains"));
    await userEvent.type(screen.getByLabelText("From"), "2026-10-05");
    await userEvent.type(screen.getByLabelText("To"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("The end date is before the start date.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("To"));
    await userEvent.click(screen.getByText("More Filters"));
    await userEvent.type(screen.getByLabelText("Record ID"), "not-a-uuid");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/A record id looks like/)).toBeInTheDocument();
    expect(nav.push).not.toHaveBeenCalled();
    expect(api.calls.length).toBe(before);
  });

  it("a hand-typed URL that fails the browser checks is not sent", async () => {
    const api = routes();
    renderWithClient(<AuditSearch params={{ actor: "x" }} />);
    expect(await screen.findByText("Give 2 to 100 characters.")).toBeInTheDocument();
    await screen.findByRole("option", { name: "All Custody Actions" });
    expect(auditCalls(api)).toHaveLength(0);
  });

  it("nothing is written: the API sees GET requests only", async () => {
    const api = routes((call: BrowserCall) =>
      call.url.includes("cursor=c1") ? { items: [row("r-3")], next_cursor: null } : { items: [row("r-1")], next_cursor: "c1" },
    );
    renderWithClient(<AuditSearch params={{}} />);
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(auditCalls(api).length).toBeGreaterThanOrEqual(3));
    expect(api.calls.every((c) => c.method === "GET")).toBe(true);
  });
});

describe("the entry page", () => {
  const ID = "0192a3b4-0000-7000-8000-000000000001";

  it("shows every detail and before and after with changed marks, nested JSON and the digest sentence", async () => {
    const api = browserApi({
      "GET /me": SUPER,
      [`GET /audit/${ID}`]: row(ID, {
        action: "office.update",
        entity_type: "office",
        before: { name: "Old name", notes: null, meta: { a: 1 }, body: { length: 42, sha256: "abcdef0123456789".repeat(4) } },
        after: { name: "New name", notes: null, meta: { a: 2 }, body: { length: 42, sha256: "abcdef0123456789".repeat(4) } },
      }),
    });
    renderWithClient(<AuditEntry id={ID} />);
    expect(await screen.findByText("office.update")).toBeInTheDocument();
    expect(screen.getByText("14 Oct 2026, 14:34:07")).toBeInTheDocument();
    expect(screen.getByText("Anita Sharma, Under Secretary, EDU")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
    expect(screen.getByText("Mozilla/5.0")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Before and After" });
    const rowOf = (field: string) => within(table).getByRole("rowheader", { name: field }).closest("tr")!;
    expect(within(rowOf("name")).getByText("Changed")).toBeInTheDocument();
    expect(within(rowOf("notes")).queryByText("Changed")).toBeNull();
    expect(within(rowOf("notes")).getAllByText("—")).toHaveLength(2);
    expect(within(rowOf("meta")).getByText(/"a": 2/)).toBeInTheDocument();
    expect(within(rowOf("body")).getAllByText("Text not kept in the log (42 characters; fingerprint abcdef012345)")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "All Entries for This Case" })).toHaveAttribute(
      "href",
      "/audit?case=ASLMS%2FGHC%2FCASE%2F2026%2F000001",
    );
    expect(screen.getByRole("link", { name: "All Entries by This Person" })).toHaveAttribute("href", "/audit?user=u-7");
    expect(screen.getByRole("link", { name: "All Entries for This Record" })).toHaveAttribute(
      "href",
      "/audit?entity_type=office&entity_id=0192a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
    );
    expect(screen.getByRole("link", { name: "Back to the Search" })).toHaveAttribute("href", "/audit");
    expect(api.calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("an action without values says so", async () => {
    browserApi({ "GET /me": SUPER, [`GET /audit/${ID}`]: row(ID, { before: null, after: {}, case: null, entity_id: null }) });
    renderWithClient(<AuditEntry id={ID} />);
    expect(await screen.findByText("This action records no values.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "All Entries for This Case" })).toBeNull();
    expect(screen.queryByRole("link", { name: "All Entries for This Record" })).toBeNull();
  });

  it("Back goes back when the entry was opened from the search", async () => {
    browserApi({ "GET /me": SUPER, [`GET /audit/${ID}`]: row(ID) });
    window.sessionStorage.setItem("aslms.audit.fromSearch", ID);
    renderWithClient(<AuditEntry id={ID} />);
    await userEvent.click(await screen.findByRole("link", { name: "Back to the Search" }));
    expect(nav.back).toHaveBeenCalled();
  });

  it("a 404 says there is no such entry; a 403 shows the readers sentence", async () => {
    browserApi({ [`GET /audit/${ID}`]: json(404, { detail: { code: "not_found", message: "no such audit row" } }) });
    const { unmount } = renderWithClient(<AuditEntry id={ID} />);
    expect(await screen.findByText("No audit entry with this id.")).toBeInTheDocument();
    unmount();
    browserApi({ [`GET /audit/${ID}`]: json(403, { detail: { code: "audit_scope", message: "no" } }) });
    renderWithClient(<AuditEntry id={ID} />);
    expect(await screen.findByText("The audit log is read only by the Super Administrator and the Auditor.")).toBeInTheDocument();
  });
});

describe("the Work list template (design portal-ui-redesign, decision 26)", () => {
  it("rows open their entry page by click or Enter, cells carry phone labels, and the page has one primary", async () => {
    routes({ items: [row("r-1"), row("r-2", { action: "custody.sent" })], next_cursor: null });
    const { container } = renderWithClient(<AuditSearch params={{}} />);
    const table = await screen.findByRole("table", { name: "Audit Log Entries" });
    const [, first, second] = within(table).getAllByRole("row");
    // every cell but the primary and the hidden View has its label for the phone card
    const labelled = [...first!.querySelectorAll("td[data-label]")].map((td) => td.getAttribute("data-label"));
    expect(labelled).toEqual(["When", "By", "Case", "Record"]);
    await userEvent.click(within(first!).getAllByRole("cell")[0]!);
    expect(nav.push).toHaveBeenCalledWith("/audit/r-1");
    expect(window.sessionStorage.getItem("aslms.audit.fromSearch")).toBe("r-1");
    second!.focus();
    await userEvent.keyboard("{Enter}");
    expect(nav.push).toHaveBeenLastCalledWith("/audit/r-2");
    // a link inside a row does its own job, not the row's
    nav.push.mockReset();
    await userEvent.click(within(second!).getByRole("link", { name: "custody.sent" }));
    expect(nav.push).not.toHaveBeenCalledWith("/audit/r-2");
    expect(screen.getByText("2 entries")).toBeInTheDocument();
    expect(primaryActions(container)).toEqual(["Search"]);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("BeforeAfter renders a DataTable with a primary cell", () => {
    renderWithClient(<BeforeAfter before={{ name: "Old name", notes: null }} after={{ name: "New name", notes: null }} />);
    const table = expectDataTable(screen.getByRole("table", { name: "Before and After" }));
    expect(within(table).getByRole("rowheader", { name: "name" }).closest("tr")!.className).toMatch(/changedRow/);
  });
});

describe("Layout B on the Audit Log (portal-ui-polish-2, decision 23)", () => {
  it("the period is the hero with Today, 7 Days and 30 Days; the fields on the right; the rest under More Filters", async () => {
    const api = routes();
    const today = istDay();
    const { container } = renderWithClient(<AuditSearch params={{ actor: "Sharma", entity_type: "case" }} />);
    await screen.findByRole("table");
    const hero = container.querySelector<HTMLElement>("[data-zone='hero']")!;
    expect(within(hero).getByRole("group", { name: "Period" })).toBeInTheDocument();
    for (const label of ["From", "To"]) expect(within(hero).getByLabelText(label)).toBeInTheDocument();
    const fields = container.querySelector<HTMLElement>("[data-zone='fields']")!;
    for (const label of ["Person", "Name Contains", "Case", "Action"]) expect(within(fields).getByLabelText(label)).toBeInTheDocument();
    expect(within(fields).getByRole("combobox", { name: "Office" })).toBeInTheDocument();
    // More Filters is open while one of its fields is in the address
    expect(screen.getByRole("button", { name: "More Filters (1)" })).toHaveAttribute("aria-expanded", "true");
    const more = container.querySelector<HTMLElement>("[data-zone='more']")!;
    for (const label of ["About the User", "Record Type", "Record ID"]) expect(within(more).getByLabelText(label)).toBeInTheDocument();
    // the strip: Newest First (no total) and the applied filters
    const strip = container.querySelector<HTMLElement>("[data-zone='summary']")!;
    expect(within(strip).getByText("Newest First")).toBeInTheDocument();
    expect(within(strip).getByText("Name Contains: Sharma")).toBeInTheDocument();
    expect(queryOf(auditCalls(api)[0]!)).toEqual({ actor: "Sharma", entity_type: "case", limit: "50" });
    // 7 Days sets From and To; a chip removes its filter
    await userEvent.click(within(hero).getByRole("button", { name: "7 Days" }));
    expect(within(hero).getByLabelText("From")).toHaveValue(addDays(today, -6));
    expect(within(hero).getByLabelText("To")).toHaveValue(today);
    expect(within(hero).getByRole("button", { name: "7 Days" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(strip).getByRole("button", { name: "Remove filter Name Contains: Sharma" }));
    expect(nav.push).toHaveBeenLastCalledWith("/audit?entity_type=case");
  });
});

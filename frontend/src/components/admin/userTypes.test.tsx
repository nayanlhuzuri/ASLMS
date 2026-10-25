import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { Permission, PermissionInfo } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { groupFunctions, UserTypePage, UserTypesIndex } from "./UserTypes";

function perm(code: string, label: string, group: string | null, group_label: string | null, sort: number | null, extra: Partial<PermissionInfo> = {}) {
  return {
    code: code as Permission,
    module: code.split(".")[0]!,
    label,
    description: `What ${label.toLowerCase()} does.`,
    is_active: group !== null,
    group,
    group_label,
    sort_in_group: sort,
    ...extra,
  } as PermissionInfo;
}

// deliberately out of order: the page follows group and sort_in_group, not the list order
const PERMS: PermissionInfo[] = [
  perm("custody.recall", "Recall cases", "case_work", "Case Work", 2),
  perm("users.view", "See users", "people", "People and access", 1),
  perm("custody.move", "Send cases held by an office", "case_work", "Case Work", 1),
  perm("users.create", "Add users", "people", "People and access", 2),
  perm("admin.tickets", "Decide admin tickets", "administration", "Administration", 1),
  perm("requests.send", "Send requests", null, null, null),
];

const SAVED = { "users.view": true, "users.create": false, "custody.move": true, "custody.recall": false, "admin.tickets": false };
const DEFAULTS = {
  dept_officer: { "users.view": true, "users.create": false, "custody.move": false, "custody.recall": false, "admin.tickets": false },
  super_admin: { "users.view": true, "users.create": true, "custody.move": true, "custody.recall": true, "admin.tickets": true },
};
const OVERVIEW = [
  { code: "super_admin", users: 1, functions_on: 5, functions_total: 5, changed_from_default: 0 },
  { code: "dept_officer", users: 12, functions_on: 2, functions_total: 5, changed_from_default: 1 },
];

const SUPER: Permission[] = ["users.view", "access.manage_types"];

function routes(functions: Permission[] = SUPER, extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(functions, functions.includes("access.manage_types") ? "super_admin" : "dept_admin"),
    "GET /reference/labels": labels(),
    "GET /admin/permissions": PERMS,
    "GET /admin/access/defaults": DEFAULTS,
    "GET /admin/access/overview": OVERVIEW,
    "GET /admin/access/types/dept_officer": SAVED,
    "GET /admin/access/types/super_admin": DEFAULTS.super_admin,
    ...extra,
  });
}

const sw = (name: string) => screen.getByRole("switch", { name });

beforeEach(() => resetNav("/admin/access/dept_officer"));

describe("the user-type cards (case-workspace-admin, decision 24)", () => {
  it("one card per type with its users, n of N functions on and n changed from default", async () => {
    resetNav("/admin/access");
    routes();
    const { container } = renderWithClient(<UserTypesIndex />);
    const list = await screen.findByRole("list", { name: "User Types" });
    const cards = within(list).getAllByRole("link");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["Super admin", "Dept officer"]);
    const officer = within(list).getByRole("link", { name: "Dept officer" });
    expect(officer).toHaveAttribute("href", "/admin/access/dept_officer");
    expect(within(officer).getByText("12 users")).toBeInTheDocument();
    expect(within(officer).getByText("2 of 5 functions on")).toBeInTheDocument();
    expect(within(officer).getByText("1 changed from default")).toBeInTheDocument();
    const root = within(list).getByRole("link", { name: "Super admin" });
    expect(within(root).getByText("1 user")).toBeInTheDocument();
    expect(within(root).queryByText(/changed from default/)).toBeNull();
    // the index has no primary (decision 28)
    expect(primaryActions(container)).toEqual([]);
  });
});

describe("the user-type page (decisions 25-27)", () => {
  it("groups follow the API's group and order, with n of m on; retired functions are not shown", async () => {
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    expect(screen.getByRole("heading", { level: 2, name: "Dept officer" })).toBeInTheDocument();
    expect(screen.getByText("12 users · 2 of 5 functions on")).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Case Work", "People and access", "Administration"]);
    const people = screen.getByRole("list", { name: "People and access" });
    expect(within(people).getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["See users", "Add users"]);
    const work = screen.getByRole("list", { name: "Case Work" });
    expect(within(work).getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["Send cases held by an office", "Recall cases"]);
    expect(screen.getAllByText("1 of 2 on", { selector: "span" })).toHaveLength(2);
    expect(screen.getByText("0 of 1 on", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Send requests" })).toBeNull();
    // each switch carries its one-line description
    expect(sw("See users")).toHaveAccessibleDescription("What see users does.");
  });

  it("every function given is under its group's heading (decision 26)", () => {
    const groups = groupFunctions(PERMS);
    expect(groups.map((g) => [g.label, g.items.map((p) => p.code)])).toEqual([
      ["Case Work", ["custody.move", "custody.recall"]],
      ["People and access", ["users.view", "users.create"]],
      ["Administration", ["admin.tickets"]],
    ]);
    expect(groups.flatMap((g) => g.items).length).toBe(PERMS.filter((p) => p.is_active).length);
  });

  it("Changed from default badges, search and Only changed from default", async () => {
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    const row = (name: string) => sw(name).closest("li")!;
    expect(within(row("Send cases held by an office")).getByText("Changed From Default")).toBeInTheDocument();
    expect(within(row("See users")).queryByText("Changed From Default")).toBeNull();
    await userEvent.type(screen.getByLabelText("Find a Function"), "recall");
    expect(screen.getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["Recall cases"]);
    await userEvent.clear(screen.getByLabelText("Find a Function"));
    await userEvent.click(screen.getByRole("button", { name: "Only Changed From Default" }));
    expect(screen.getByRole("button", { name: "Only Changed From Default" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["Send cases held by an office"]);
    await userEvent.type(screen.getByLabelText("Find a Function"), "nothing like this");
    expect(screen.getByText("No function matches.")).toBeInTheDocument();
  });

  it("the Save bar counts against the saved state; Discard clears; Reset to default changes the draft only", async () => {
    const api = routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    const bar = screen.getByRole("region", { name: "Unsaved Changes" });
    expect(within(bar).getByText("No unsaved changes")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Save Changes" })).toBeDisabled();
    await userEvent.click(sw("Add users"));
    await userEvent.click(sw("Recall cases"));
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
    expect(within(bar).getByText("2 unsaved changes")).toBeInTheDocument();
    // switching one back counts against the saved state
    await userEvent.click(sw("Recall cases"));
    expect(within(bar).getByText("1 unsaved change")).toBeInTheDocument();
    await userEvent.click(within(bar).getByRole("button", { name: "Discard" }));
    expect(within(bar).getByText("No unsaved changes")).toBeInTheDocument();
    expect(sw("Add users")).toHaveAttribute("aria-checked", "false");
    // Reset to default: Send cases held by an office goes back to off, nothing is sent
    await userEvent.click(screen.getByRole("button", { name: "Reset to Default" }));
    expect(sw("Send cases held by an office")).toHaveAttribute("aria-checked", "false");
    expect(within(bar).getByText("1 unsaved change")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("Save sends one PUT with only the changed entries, then says it is in the audit log", async () => {
    const api = routes(SUPER, {
      "PUT /admin/access/types/dept_officer": { ...SAVED, "users.create": true, "custody.recall": true },
    });
    const { container } = renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    await userEvent.click(sw("Add users"));
    await userEvent.click(sw("Recall cases"));
    expect(primaryActions(container)).toEqual(["Save Changes"]);
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("Saved. The change is in the audit log.")).toBeInTheDocument();
    const puts = api.calls.filter((c) => c.method === "PUT");
    expect(puts).toHaveLength(1);
    expect(puts[0]!.path).toBe("/admin/access/types/dept_officer");
    expect(puts[0]!.body).toEqual({
      changes: [
        { permission: "custody.recall", enabled: true },
        { permission: "users.create", enabled: true },
      ],
    });
    expect(screen.getByText("No unsaved changes")).toBeInTheDocument();
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
  });

  it("a 400 names the function and keeps the draft", async () => {
    routes(SUPER, {
      "PUT /admin/access/types/dept_officer": json(400, { detail: { code: "retired", message: "users.create is retired" } }),
    });
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    await userEvent.click(sw("Add users"));
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("Nothing was saved. Add users: users.create is retired")).toBeInTheDocument();
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
  });

  it("the super admin type is all on and locked; admin.tickets is reserved", async () => {
    resetNav("/admin/access/super_admin");
    routes();
    const { unmount } = renderWithClient(<UserTypePage role="super_admin" />);
    await screen.findByRole("switch", { name: "See users" });
    expect(screen.getByText("The Super Administrator always holds every function.")).toBeInTheDocument();
    for (const s of screen.getAllByRole("switch")) {
      expect(s).toHaveAttribute("aria-checked", "true");
      expect(s).toBeDisabled();
    }
    expect(screen.queryByRole("region", { name: "Unsaved Changes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset to Default" })).toBeNull();
    unmount();
    resetNav("/admin/access/dept_officer");
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    const tickets = await screen.findByRole("switch", { name: "Decide admin tickets" });
    expect(tickets).toBeDisabled();
    expect(tickets).toHaveAccessibleDescription("Reserved to the Super Administrator");
    expect(sw("See users")).toBeEnabled();
  });

  it("without access.manage_types every switch is disabled and the bar says who changes user types", async () => {
    routes(["users.view"]);
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    for (const s of screen.getAllByRole("switch")) expect(s).toBeDisabled();
    expect(screen.queryByRole("region", { name: "Unsaved Changes" })).toBeNull();
    expect(screen.getByText("Only the Super Administrator changes user types.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset to Default" })).toBeNull();
  });

  it("leaving with unsaved changes asks first; Stay keeps the draft, Leave goes", async () => {
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    // no question without changes
    const back = screen.getByRole("link", { name: /All User Types/ });
    back.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(back);
    expect(screen.queryByRole("dialog", { name: "Leave Without Saving?" })).toBeNull();
    await userEvent.click(sw("Add users"));
    await userEvent.click(back);
    const dialog = await screen.findByRole("dialog", { name: "Leave Without Saving?" });
    expect(within(dialog).getByText("1 change is not saved and will be lost.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave Without Saving?" })).toBeNull());
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
    expect(nav.push).not.toHaveBeenCalled();
    await userEvent.click(back);
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Leave Without Saving?" })).getByRole("button", { name: "Leave" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/access");
    // closing the tab asks too
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("Edit Name (design portal-ui-polish-2, decisions 12 and 13)", () => {
  it("shows Edit Name only with access.manage_types, with the code as a tag in the header", async () => {
    routes(["users.view"]);
    const { unmount } = renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    expect(screen.queryByRole("button", { name: "Edit Name" })).toBeNull();
    expect(screen.getByText("dept_officer", { selector: "code" })).toBeInTheDocument();
    unmount();
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    expect(await screen.findByRole("button", { name: "Edit Name" })).toBeInTheDocument();
  });

  it("counts the characters, warns about an empty or taken name and shows the server's 409 on the field", async () => {
    const api = routes(SUPER, {
      "PATCH /admin/access/types/dept_officer/name": json(409, { detail: { code: "label_taken", message: "another user type already has this name" } }),
    });
    renderWithClient(<UserTypePage role="dept_officer" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Name" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Name" });
    expect(within(dialog).getByText("Internal code: dept_officer")).toBeInTheDocument();
    const name = within(dialog).getByLabelText("Display Name");
    expect(name).toHaveValue("Dept officer");
    expect(within(dialog).getByText("12 / 80 characters")).toBeInTheDocument();
    expect(within(dialog).getByText("0 / 200 characters")).toBeInTheDocument();
    await userEvent.clear(name);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Give the user type a name.")).toBeInTheDocument();
    // another type's name, without regard to case, is warned about before sending
    await userEvent.type(name, "auditor");
    expect(within(dialog).getByText("Another user type already has this name.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
    // a clash only the server sees is shown on the field too
    await userEvent.clear(name);
    await userEvent.type(name, "Officer of the Day");
    expect(within(dialog).queryByText("Another user type already has this name.")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Another user type already has this name.")).toBeInTheDocument();
    expect(name).toHaveAccessibleDescription(expect.stringContaining("Another user type already has this name."));
  });

  it("saves the trimmed values, drops the labels and cards and shows the new name", async () => {
    let current = labels();
    const api = routes(SUPER, {
      "GET /reference/labels": () => current,
      "PATCH /admin/access/types/dept_officer/name": (call: { body: unknown }) => {
        const body = call.body as { label: string; description: string | null };
        current = {
          ...current,
          user_types: current.user_types.map((t) => (t.code === "dept_officer" ? { ...t, label: body.label, description: body.description } : t)),
        };
        return { code: "dept_officer", label: body.label, description: body.description, changed: true };
      },
    });
    renderWithClient(<UserTypePage role="dept_officer" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Name" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Name" });
    const name = within(dialog).getByLabelText("Display Name");
    await userEvent.clear(name);
    await userEvent.type(name, "  Department   Officer (Legal) ");
    await userEvent.type(within(dialog).getByLabelText("Short Description"), "  Works on cases.  ");
    const before = api.calls.filter((c) => c.path.startsWith("/admin/access/overview")).length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit Name" })).toBeNull());
    const patch = api.calls.find((c) => c.method === "PATCH")!;
    expect(patch.path).toBe("/admin/access/types/dept_officer/name");
    expect(patch.body).toEqual({ label: "Department Officer (Legal)", description: "Works on cases." });
    expect(await screen.findByRole("heading", { level: 2, name: "Department Officer (Legal)" })).toBeInTheDocument();
    expect(screen.getByText("Name saved. The change is recorded in the audit log.")).toBeInTheDocument();
    await waitFor(() => expect(api.calls.filter((c) => c.path.startsWith("/admin/access/overview")).length).toBeGreaterThan(before));
    // one primary per page: the dialog's Save is gone and Save Changes stays the page's primary
    expect(screen.getByRole("button", { name: "Save Changes" })).toHaveAttribute("data-variant", "primary");
  });

  it("the Jump To list links to each function group's anchor", async () => {
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    const jump = screen.getByRole("navigation", { name: "Jump To" });
    const links = within(jump).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Case Work", "#group-case_work"],
      ["People and access", "#group-people"],
      ["Administration", "#group-administration"],
    ]);
    for (const l of links) expect(document.querySelector(l.getAttribute("href")!)).not.toBeNull();
    // the phone form is a select over the same groups
    const select = screen.getByRole("combobox", { name: "Jump To" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose a Group",
      "Case Work",
      "People and access",
      "Administration",
    ]);
  });
});

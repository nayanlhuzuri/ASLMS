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
  perm("custody.recall", "Recall cases", "case_work", "Case work", 2),
  perm("users.view", "See users", "people", "People and access", 1),
  perm("custody.move", "Send cases held by an office", "case_work", "Case work", 1),
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
    const list = await screen.findByRole("list", { name: "User types" });
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
    expect(headings).toEqual(["Case work", "People and access", "Administration"]);
    const people = screen.getByRole("list", { name: "People and access" });
    expect(within(people).getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["See users", "Add users"]);
    const work = screen.getByRole("list", { name: "Case work" });
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
      ["Case work", ["custody.move", "custody.recall"]],
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
    expect(within(row("Send cases held by an office")).getByText("Changed from default")).toBeInTheDocument();
    expect(within(row("See users")).queryByText("Changed from default")).toBeNull();
    await userEvent.type(screen.getByLabelText("Find a function"), "recall");
    expect(screen.getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["Recall cases"]);
    await userEvent.clear(screen.getByLabelText("Find a function"));
    await userEvent.click(screen.getByRole("button", { name: "Only changed from default" }));
    expect(screen.getByRole("button", { name: "Only changed from default" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("switch").map((s) => s.getAttribute("aria-label"))).toEqual(["Send cases held by an office"]);
    await userEvent.type(screen.getByLabelText("Find a function"), "nothing like this");
    expect(screen.getByText("No function matches.")).toBeInTheDocument();
  });

  it("the Save bar counts against the saved state; Discard clears; Reset to default changes the draft only", async () => {
    const api = routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    const bar = screen.getByRole("region", { name: "Unsaved changes" });
    expect(within(bar).getByText("No unsaved changes")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Save changes" })).toBeDisabled();
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
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));
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
    expect(primaryActions(container)).toEqual(["Save changes"]);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Nothing was saved. Add users: users.create is retired")).toBeInTheDocument();
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
  });

  it("the super admin type is all on and locked; admin.tickets is reserved", async () => {
    resetNav("/admin/access/super_admin");
    routes();
    const { unmount } = renderWithClient(<UserTypePage role="super_admin" />);
    await screen.findByRole("switch", { name: "See users" });
    expect(screen.getByText("The super admin always holds every function.")).toBeInTheDocument();
    for (const s of screen.getAllByRole("switch")) {
      expect(s).toHaveAttribute("aria-checked", "true");
      expect(s).toBeDisabled();
    }
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset to default" })).toBeNull();
    unmount();
    resetNav("/admin/access/dept_officer");
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    const tickets = await screen.findByRole("switch", { name: "Decide admin tickets" });
    expect(tickets).toBeDisabled();
    expect(tickets).toHaveAccessibleDescription("Reserved to the super admin");
    expect(sw("See users")).toBeEnabled();
  });

  it("without access.manage_types every switch is disabled and the bar says who changes user types", async () => {
    routes(["users.view"]);
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    for (const s of screen.getAllByRole("switch")) expect(s).toBeDisabled();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    expect(screen.getByText("Only the super admin changes user types.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset to default" })).toBeNull();
  });

  it("leaving with unsaved changes asks first; Stay keeps the draft, Leave goes", async () => {
    routes();
    renderWithClient(<UserTypePage role="dept_officer" />);
    await screen.findByRole("switch", { name: "See users" });
    // no question without changes
    const back = screen.getByRole("link", { name: /All user types/ });
    back.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(back);
    expect(screen.queryByRole("dialog", { name: "Leave without saving?" })).toBeNull();
    await userEvent.click(sw("Add users"));
    await userEvent.click(back);
    const dialog = await screen.findByRole("dialog", { name: "Leave without saving?" });
    expect(within(dialog).getByText("1 change is not saved and will be lost.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Leave without saving?" })).toBeNull());
    expect(sw("Add users")).toHaveAttribute("aria-checked", "true");
    expect(nav.push).not.toHaveBeenCalled();
    await userEvent.click(back);
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Leave without saving?" })).getByRole("button", { name: "Leave" }));
    expect(nav.push).toHaveBeenCalledWith("/admin/access");
    // closing the tab asks too
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});

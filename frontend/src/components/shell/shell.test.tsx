import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AdminFrame } from "@/components/admin/AdminFrame";
import type { Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, labels, makeMe, renderWithClient } from "@/test/render";

import { AlertBell, PortalShell, Sidebar } from "./PortalShell";

const OFFICER: Permission[] = ["cases.view_scope", "notes.add", "documents.view", "alerts.acknowledge"];
const DEPT_ADMIN: Permission[] = [
  "cases.view_scope",
  "users.view",
  "users.create",
  "users.edit",
  "users.set_type",
  "users.enable_disable",
  "users.grant",
  "users.propose_head",
  "offices.manage",
];

beforeEach(() => {
  resetNav("/");
});

describe("navigation by functions", () => {
  it("an officer sees no Administration and no unbuilt entries", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByRole("link", { name: "Administration" })).toBeNull();
    for (const unbuilt of ["Case inbox", "Search", "Alerts & calendar", "Reports", "Audit log", "Data collection"]) {
      expect(within(nav).queryByRole("link", { name: unbuilt })).toBeNull();
    }
  });

  it("a department admin sees Administration with Users and Offices", async () => {
    resetNav("/admin/users");
    const me = makeMe(DEPT_ADMIN, "dept_admin");
    browserApi({ "GET /reference/labels": labels(), "GET /me": me });
    renderWithClient(<Sidebar me={me} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Administration" })).toHaveAttribute("aria-current", "page");
  });

  it("the administration tabs follow the functions", async () => {
    resetNav("/admin/users");
    const me = makeMe(DEPT_ADMIN, "dept_admin");
    browserApi({ "GET /me": me });
    renderWithClient(
      <AdminFrame>
        <p>body</p>
      </AdminFrame>,
    );
    const tabs = await screen.findByRole("navigation", { name: "Administration sections" });
    expect(within(tabs).getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Offices" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Tickets" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "User types" })).toBeInTheDocument();
  });

  it("an officer's administration has no tabs", async () => {
    browserApi({ "GET /me": makeMe(OFFICER) });
    renderWithClient(
      <AdminFrame>
        <p>body</p>
      </AdminFrame>,
    );
    await screen.findByText("body");
    expect(screen.queryByRole("navigation", { name: "Administration sections" })).toBeNull();
  });
});

describe("header and sidebar foot", () => {
  it("the alert badge shows the unread count from /alerts/counts", async () => {
    browserApi({ "GET /alerts/counts": { unread: 7, open: { critical: 1, high: 2, normal: 4 } } });
    renderWithClient(<AlertBell me={makeMe(OFFICER)} />);
    expect(await screen.findByRole("link", { name: "7 unread alerts" })).toHaveAttribute("href", "/#alerts");
  });

  it("no bell for a login without case functions", () => {
    const api = browserApi({});
    renderWithClient(<AlertBell me={makeMe(["users.view"])} />);
    expect(screen.queryByRole("link", { name: /unread/ })).toBeNull();
    expect(api.calls).toHaveLength(0);
  });

  it("the foot names the person and the primary office and lists every membership", async () => {
    const me = makeMe(OFFICER, "dept_officer", {
      memberships: [
        {
          id: "m-1",
          office: { code: "EDU", name: "Education", kind: "department" },
          department_code: "EDU",
          designation: "Under Secretary",
          role: "dept_officer",
          is_primary: true,
          is_active: true,
        },
        {
          id: "m-2",
          office: { code: "HEALTH", name: "Health", kind: "department" },
          department_code: "HEALTH",
          designation: "Joint Secretary",
          role: "dept_officer",
          is_primary: false,
          is_active: true,
        },
      ],
    });
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={me} />);
    expect(screen.getByText("Anita Sharma")).toBeInTheDocument();
    expect(screen.getByText("Under Secretary")).toBeInTheDocument();
    expect(screen.getByText("Education")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "2 offices" }));
    const list = screen.getByRole("list", { name: "2 offices" });
    expect(within(list).getByText(/Joint Secretary, Health/)).toBeInTheDocument();
    expect(within(list).getByText(/Under Secretary, Education .*\(primary\)/)).toBeInTheDocument();
  });

  it("the shell loads /me and shows the frame", async () => {
    browserApi({
      "GET /me": makeMe(OFFICER),
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 0, open: { critical: 0, high: 0, normal: 0 } },
    });
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    expect(await screen.findByText("page body")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "User menu" })).toBeInTheDocument());
  });
});

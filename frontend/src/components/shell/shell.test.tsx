import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AdminFrame } from "@/components/admin/AdminFrame";
import { MappingFrame } from "@/components/admin/mapping/MappingFrame";
import type { Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, labels, makeMe, renderWithClient } from "@/test/render";

import { nav } from "@/test/nav";

import { AlertBell, HeaderSearch, PortalShell, Sidebar } from "./PortalShell";

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
    for (const unbuilt of ["Alerts & calendar", "Reports", "Audit log", "Data collection"]) {
      expect(within(nav).queryByRole("link", { name: unbuilt })).toBeNull();
    }
  });

  it("Case inbox shows with a department membership, Search for every case reader", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Case inbox" })).toHaveAttribute("href", "/inbox");
    expect(within(nav).getByRole("link", { name: "Search" })).toHaveAttribute("href", "/search");
  });

  it("standing counsel without a department use Search, not the inbox", () => {
    browserApi({ "GET /reference/labels": labels() });
    const counsel = makeMe(["cases.view_scope", "documents.view"], "standing_counsel", {
      memberships: [
        {
          id: "m-9",
          office: { code: "GOA-SC", name: "Standing Counsel", kind: "unit" },
          department_code: null,
          designation: null,
          role: "standing_counsel",
          is_primary: true,
          is_active: true,
        },
      ],
    });
    renderWithClient(<Sidebar me={counsel} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).queryByRole("link", { name: "Case inbox" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Search" })).toBeInTheDocument();
  });

  it("a State-wide reader without a department sees the inbox through cases.view_all", () => {
    browserApi({ "GET /reference/labels": labels() });
    const reader = makeMe(["cases.view_scope", "cases.view_all"], "state_oversight", { memberships: [] });
    renderWithClient(<Sidebar me={reader} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Case inbox" })).toBeInTheDocument();
  });

  it("a login without case functions sees neither", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["users.view"], "dept_admin")} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).queryByRole("link", { name: "Case inbox" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Search" })).toBeNull();
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

describe("department mapping tab", () => {
  const MAPPING_ADMIN: Permission[] = [...DEPT_ADMIN, "admin.counsel_codes", "admin.keywords", "admin.watchlist"];

  async function adminTabs(me: ReturnType<typeof makeMe>) {
    browserApi({ "GET /me": me });
    renderWithClient(
      <AdminFrame>
        <p>body</p>
      </AdminFrame>,
    );
    await screen.findByText("body");
    return screen.queryByRole("navigation", { name: "Administration sections" });
  }

  it("a department admin sees Department mapping", async () => {
    resetNav("/admin/mapping/codes");
    const tabs = await adminTabs(makeMe(MAPPING_ADMIN, "dept_admin"));
    expect(within(tabs!).getByRole("link", { name: "Department mapping" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs!).getByRole("link", { name: "Department mapping" })).toHaveAttribute("href", "/admin/mapping");
  });

  it("a department officer does not", async () => {
    const tabs = await adminTabs(makeMe(OFFICER));
    expect(tabs).toBeNull();
    expect(screen.queryByRole("link", { name: "Department mapping" })).toBeNull();
  });

  it("a login holding only admin.watchlist reaches Administration with the mapping tab and without Designations", async () => {
    const me = makeMe(["admin.watchlist"], "central_operator");
    browserApi({ "GET /reference/labels": labels(), "GET /me": me });
    const { unmount } = renderWithClient(<Sidebar me={me} />);
    const side = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(side).getByRole("link", { name: "Administration" })).toHaveAttribute("href", "/admin");
    unmount();
    const tabs = await adminTabs(me);
    expect(within(tabs!).getByRole("link", { name: "Department mapping" })).toBeInTheDocument();
    expect(within(tabs!).queryByRole("link", { name: "Designations" })).toBeNull();
  });

  it("the super admin sees it", async () => {
    const tabs = await adminTabs(makeMe([...MAPPING_ADMIN, "admin.scoring", "admin.designations"], "super_admin"));
    expect(within(tabs!).getByRole("link", { name: "Department mapping" })).toBeInTheDocument();
    expect(within(tabs!).getByRole("link", { name: "Designations" })).toBeInTheDocument();
  });

  async function mappingTabs(functions: Permission[]) {
    browserApi({ "GET /me": makeMe(functions, "dept_admin") });
    renderWithClient(
      <MappingFrame>
        <p>tab body</p>
      </MappingFrame>,
    );
    await screen.findByText("tab body");
    const nav = screen.getByRole("navigation", { name: "Department mapping sections" });
    return within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
  }

  it("the mapping sub-tabs follow the functions", async () => {
    expect(await mappingTabs(["admin.watchlist"])).toEqual(["Watchlist"]);
  });

  it("Scoring shows for admin.keywords without admin.scoring", async () => {
    expect(await mappingTabs(["admin.keywords"])).toEqual(["Keywords and name patterns", "Scoring"]);
  });

  it("every tab for the super admin's functions", async () => {
    expect(await mappingTabs(["admin.counsel_codes", "admin.keywords", "admin.watchlist", "admin.scoring"])).toEqual([
      "Counsel codes",
      "Keywords and name patterns",
      "Watchlist",
      "Scoring",
    ]);
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

  it("the header search box opens /search?q= for case readers", async () => {
    browserApi({});
    renderWithClient(<HeaderSearch me={makeMe(OFFICER)} />);
    const box = screen.getByRole("searchbox", { name: "Search by CINO, case number or party name" });
    await userEvent.type(box, "WP(C) 4326/2025");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.push).toHaveBeenCalledWith("/search?q=WP(C)%204326%2F2025");
  });

  it("no header search box without case functions", () => {
    browserApi({});
    renderWithClient(<HeaderSearch me={makeMe(["users.view"])} />);
    expect(screen.queryByRole("search")).toBeNull();
  });
});

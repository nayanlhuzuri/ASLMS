import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFrame } from "@/components/admin/AdminFrame";
import { MappingFrame } from "@/components/admin/mapping/MappingFrame";
import { PageHeader } from "@/components/ui";
import { BRAND } from "@/lib/brand";
import type { Permission } from "@/lib/api/types";
import { bottomBarFor } from "@/lib/routes";
import { resetNav } from "@/test/nav";
import { browserApi, labels, makeMe, renderWithClient } from "@/test/render";

import { nav } from "@/test/nav";

import { Brand } from "./Brand";
import { AlertBell, Breadcrumb, HeaderSearch, PortalShell, Sidebar } from "./PortalShell";

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
  it("Work lists Case inbox, Cause list, My calendar, Alerts and Search in order for a case reader; no Cases entry (case-inbox-merge, decision 6)", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    const names = within(nav)
      .getAllByRole("treeitem")
      .map((a) => a.textContent);
    expect(names).toEqual(["Dashboard", "Case Inbox", "Cause List", "My Calendar", "Alerts", "Search"]);
    expect(within(nav).getByRole("treeitem", { name: "Cause List" })).toHaveAttribute("href", "/causelist");
    expect(within(nav).queryByRole("treeitem", { name: "Cases" })).toBeNull();
    expect(within(nav).getByRole("treeitem", { name: "My Calendar" })).toHaveAttribute("href", "/calendar");
    expect(within(nav).getByRole("treeitem", { name: "Alerts" })).toHaveAttribute("href", "/alerts");
  });

  it("Reports and Audit log sit under Oversight, Data collection and Administration under Settings", () => {
    browserApi({ "GET /reference/labels": labels() });
    const me = makeMe(["cases.view_all", "reports.state", "audit.view", "users.view"], "super_admin");
    renderWithClient(<Sidebar me={me} />);
    const oversight = screen.getByRole("tree", { name: "Oversight" });
    expect(
      within(oversight)
        .getAllByRole("treeitem")
        .map((a) => a.textContent),
    ).toEqual(["Reports", "Audit Log"]);
    const settings = screen.getByRole("tree", { name: "Settings" });
    expect(
      within(settings)
        .getAllByRole("treeitem")
        .map((a) => a.textContent),
    ).toEqual(["Data Collection", "Administration"]);
    expect(within(screen.getByRole("tree", { name: "Work" })).getByRole("treeitem", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("a group with no visible entry is hidden", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    expect(screen.getByRole("tree", { name: "Work" })).toBeInTheDocument();
    expect(screen.queryByRole("tree", { name: "Oversight" })).toBeNull();
    expect(screen.queryByRole("tree", { name: "Settings" })).toBeNull();
    expect(screen.queryByText("Oversight")).toBeNull();
  });

  it("the Alerts entry shows the unread count from /alerts/counts in its pill", async () => {
    browserApi({
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 3, open: { critical: 0, high: 1, normal: 2 } },
    });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const link = await screen.findByRole("treeitem", { name: "Alerts, 3" });
    expect(link).toHaveAttribute("href", "/alerts");
    expect(within(link).getByText("3")).toHaveAttribute("aria-hidden", "true");
  });

  it("Reports shows with a reports function, before Data collection (portal-reports)", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["cases.view_all", "reports.state"], "state_oversight")} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    const names = within(nav)
      .getAllByRole("treeitem")
      .map((a) => a.textContent);
    expect(names.indexOf("Data Collection")).toBe(names.indexOf("Reports") + 1);
    expect(within(nav).getByRole("treeitem", { name: "Reports" })).toHaveAttribute("href", "/reports");
  });

  it("Case inbox stays current across its tabs and on a case page", () => {
    for (const path of ["/inbox/sent", "/inbox/pending", "/cases/EDU-2026-0001", "/cases/EDU-2026-0001/notes"]) {
      resetNav(path);
      browserApi({ "GET /reference/labels": labels() });
      const { unmount } = renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
      const nav = screen.getByRole("navigation", { name: "Main Navigation" });
      expect(within(nav).getByRole("treeitem", { name: "Case Inbox" }), path).toHaveAttribute("aria-current", "page");
      unmount();
    }
  });

  it("an officer sees no Administration and no unbuilt entries", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).getByRole("treeitem", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByRole("treeitem", { name: "Administration" })).toBeNull();
    for (const unbuilt of ["Reports", "Audit Log", "Data Collection"]) {
      expect(within(nav).queryByRole("treeitem", { name: unbuilt })).toBeNull();
    }
  });

  it("Case inbox shows with a department membership, Search for every case reader", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).getByRole("treeitem", { name: "Case Inbox" })).toHaveAttribute("href", "/inbox");
    expect(within(nav).getByRole("treeitem", { name: "Search" })).toHaveAttribute("href", "/search");
  });

  it("standing counsel without a department see the Case inbox and Search, not Case claim (case-inbox-merge, decision 6)", () => {
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
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).getByRole("treeitem", { name: "Case Inbox" })).toHaveAttribute("href", "/inbox");
    expect(within(nav).queryByRole("treeitem", { name: /Case Claim/ })).toBeNull();
    expect(within(nav).getByRole("treeitem", { name: "Search" })).toBeInTheDocument();
  });

  it("a State-wide reader without a department sees the inbox through cases.view_all", () => {
    browserApi({ "GET /reference/labels": labels() });
    const reader = makeMe(["cases.view_scope", "cases.view_all"], "state_oversight", { memberships: [] });
    renderWithClient(<Sidebar me={reader} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).getByRole("treeitem", { name: "Case Inbox" })).toBeInTheDocument();
  });

  it("a login without case functions sees neither", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["users.view"], "dept_admin")} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).queryByRole("treeitem", { name: "Case Inbox" })).toBeNull();
    expect(within(nav).queryByRole("treeitem", { name: "Search" })).toBeNull();
  });

  it("a department admin sees Administration with Users and Offices", async () => {
    resetNav("/admin/users");
    const me = makeMe(DEPT_ADMIN, "dept_admin");
    browserApi({ "GET /reference/labels": labels(), "GET /me": me });
    renderWithClient(<Sidebar me={me} />);
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    // design portal-ui-polish-2, decision 16: the parent is on the path and open; its active child is the page
    const admin = within(nav).getByRole("treeitem", { name: "Administration" });
    expect(admin).toHaveAttribute("aria-expanded", "true");
    expect(admin).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("treeitem", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("treeitem", { name: "Offices" })).toHaveAttribute("href", "/admin/offices");
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
    const tabs = await screen.findByRole("navigation", { name: "Administration Sections" });
    expect(within(tabs).getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Offices" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Tickets" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "User Types" })).toBeInTheDocument();
  });

  it("an officer's administration has no tabs", async () => {
    browserApi({ "GET /me": makeMe(OFFICER) });
    renderWithClient(
      <AdminFrame>
        <p>body</p>
      </AdminFrame>,
    );
    await screen.findByText("body");
    expect(screen.queryByRole("navigation", { name: "Administration Sections" })).toBeNull();
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
    return screen.queryByRole("navigation", { name: "Administration Sections" });
  }

  it("a department admin sees Department mapping", async () => {
    resetNav("/admin/mapping/codes");
    const tabs = await adminTabs(makeMe(MAPPING_ADMIN, "dept_admin"));
    expect(within(tabs!).getByRole("link", { name: "Department Mapping" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs!).getByRole("link", { name: "Department Mapping" })).toHaveAttribute("href", "/admin/mapping");
  });

  it("a department officer does not", async () => {
    const tabs = await adminTabs(makeMe(OFFICER));
    expect(tabs).toBeNull();
    expect(screen.queryByRole("link", { name: "Department Mapping" })).toBeNull();
  });

  it("a login holding only admin.watchlist reaches Administration with the mapping tab and without Designations", async () => {
    const me = makeMe(["admin.watchlist"], "central_operator");
    browserApi({ "GET /reference/labels": labels(), "GET /me": me });
    const { unmount } = renderWithClient(<Sidebar me={me} />);
    const side = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(side).getByRole("treeitem", { name: "Administration" })).toHaveAttribute("href", "/admin");
    unmount();
    const tabs = await adminTabs(me);
    expect(within(tabs!).getByRole("link", { name: "Department Mapping" })).toBeInTheDocument();
    expect(within(tabs!).queryByRole("link", { name: "Designations" })).toBeNull();
  });

  it("the super admin sees it", async () => {
    const tabs = await adminTabs(makeMe([...MAPPING_ADMIN, "admin.scoring", "admin.designations"], "super_admin"));
    expect(within(tabs!).getByRole("link", { name: "Department Mapping" })).toBeInTheDocument();
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
    const nav = screen.getByRole("navigation", { name: "Department Mapping Sections" });
    return within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
  }

  it("the mapping sub-tabs follow the functions", async () => {
    expect(await mappingTabs(["admin.watchlist"])).toEqual(["Watchlist"]);
  });

  it("Scoring shows for admin.keywords without admin.scoring", async () => {
    expect(await mappingTabs(["admin.keywords"])).toEqual(["Keywords and Name Patterns", "Court Search", "Scoring"]);
  });

  it("every tab for the super admin's functions", async () => {
    expect(await mappingTabs(["admin.counsel_codes", "admin.keywords", "admin.watchlist", "admin.scoring"])).toEqual([
      "Counsel Codes",
      "Keywords and Name Patterns",
      "Court Search",
      "Watchlist",
      "Scoring",
    ]);
  });
});

describe("header and sidebar foot", () => {
  it("the alert badge shows the unread count from /alerts/counts", async () => {
    browserApi({ "GET /alerts/counts": { unread: 7, open: { critical: 1, high: 2, normal: 4 } } });
    renderWithClient(<AlertBell me={makeMe(OFFICER)} />);
    expect(await screen.findByRole("link", { name: "7 unread alerts" })).toHaveAttribute("href", "/alerts");
  });

  it("the breadcrumb names the Case inbox and Alerts screens by path, the case tab by segment", () => {
    for (const [path, last] of [
      ["/inbox/working", "Working On"],
      ["/inbox/pending", "Pending Action"],
      ["/inbox/sent", "Sent by Me"],
      ["/alerts", "Alerts"],
      ["/calendar", "My Calendar"],
      ["/alerts/calendar", "Hearing Calendar"],
      ["/cases/EDU-2026-0001/alerts", "Alerts"],
      ["/admin/offices", "Offices"],
      ["/reports/pending-cases", "Pending Cases"],
      ["/reports/data-health", "Data Collection Health"],
    ] as const) {
      resetNav(path);
      const { unmount } = renderWithClient(<Breadcrumb />);
      const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
      expect(within(crumbs).getByText(last, { selector: "[aria-current=page]" })).toBeInTheDocument();
      unmount();
    }
    // design case-inbox-merge, decision 12: the crumb above a case page reads "Case inbox" and leads to /cases
    resetNav("/cases/EDU-2026-0001/alerts");
    renderWithClient(<Breadcrumb />);
    expect(screen.getByRole("link", { name: "Case Inbox" })).toHaveAttribute("href", "/cases");
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
    expect(within(list).getByText(/Under Secretary, Education .*(Primary)/)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByRole("button", { name: "User Menu" })).toBeInTheDocument());
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

describe("header, brand, drawer and bottom bar (portal-ui-redesign, decisions 18, 21 and 22)", () => {
  const shellApi = (me = makeMe(OFFICER)) =>
    browserApi({
      "GET /me": me,
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 2, open: { critical: 0, high: 0, normal: 2 } },
    });

  it("the emblem slot is a marked placeholder hidden from screen readers while no emblem is set", () => {
    renderWithClient(<Brand brand={{ emblem: null }} />);
    const slot = screen.getByText("Emblem");
    expect(slot).toHaveAttribute("title", "Place for the Official Government of Assam Emblem");
    expect(slot).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("Government of Assam")).toBeInTheDocument();
    expect(screen.getByText("Assam State Litigation Management System")).toBeInTheDocument();
  });

  it("with an emblem file set, the header shows the image with its alternative text at 40 px high", () => {
    renderWithClient(<Brand brand={{ emblem: { src: "/brand/emblem.svg", width: 160, height: 200 } }} />);
    const img = screen.getByRole("img", { name: "Emblem of the Government of Assam" });
    expect(img).toHaveAttribute("src", "/brand/emblem.svg");
    expect(img).toHaveAttribute("height", "40");
    expect(img).toHaveAttribute("width", "32");
    expect(screen.queryByText("Emblem")).toBeNull();
  });

  it("the configured emblem files are the official ones the owner supplied, present under public/brand/", () => {
    const dir = join(process.cwd(), "public", "brand");
    const files = existsSync(dir) ? readdirSync(dir).filter((f) => f !== ".gitkeep") : [];
    expect(files.sort()).toEqual(["assam-emblem-lockup.png", "assam-emblem-mark.png"]);
    expect(BRAND.emblem?.src).toBe("/brand/assam-emblem-mark.png");
    expect(BRAND.lockup?.src).toBe("/brand/assam-emblem-lockup.png");
  });

  it("the header shows the official emblem by default", () => {
    renderWithClient(<Brand />);
    const img = screen.getByRole("img", { name: "Emblem of the Government of Assam" });
    expect(img).toHaveAttribute("src", "/brand/assam-emblem-mark.png");
    expect(img).toHaveAttribute("height", "40");
  });

  it("the header shows the brand, the search box, the bell and the avatar menu; no breadcrumb", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    const header = await screen.findByRole("banner");
    expect(within(header).getByText("Assam State Litigation Management System")).toBeInTheDocument();
    expect(within(header).getByRole("searchbox")).toBeInTheDocument();
    expect(await within(header).findByRole("link", { name: "2 unread alerts" })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "User Menu" })).toHaveTextContent("AS");
    expect(within(header).queryByRole("navigation", { name: "Breadcrumb" })).toBeNull();
  });

  it("the avatar menu opens and closes by keyboard and lists My profile and Sign out", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    const button = await screen.findByRole("button", { name: "User Menu" });
    button.focus();
    await userEvent.keyboard("{ArrowDown}");
    const menu = screen.getByRole("menu", { name: "User Menu" });
    expect(within(menu).getByRole("menuitem", { name: "My Profile" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Sign Out" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("the drawer opens from the menu button, traps focus and closes on Escape and on the overlay", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    const open = await screen.findByRole("button", { name: "Open Menu" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    const drawer = screen.getByRole("dialog", { name: "Main Navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(drawer.contains(document.activeElement)).toBe(true);
    // Tab past the last control comes back to the first: the focus stays in the drawer
    for (let i = 0; i < 20; i += 1) await userEvent.tab();
    expect(drawer.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Main Navigation" })).toBeNull();
    expect(open).toHaveFocus();
    await userEvent.click(open);
    await userEvent.click(screen.getByTestId("drawer-overlay"));
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("drawer-overlay")).toBeNull();
  });

  it("the drawer's top carries the brand and the search box for phones", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    await screen.findByText("page body");
    expect(screen.getAllByRole("search")).toHaveLength(2);
    expect(document.getElementById("drawer-search")).toHaveAccessibleName("Search by CINO, case number or party name");
  });

  it("the bottom bar shows at most three entries plus More, which opens the drawer", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    const bar = await screen.findByRole("navigation", { name: "Quick Links" });
    expect(
      within(bar)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Dashboard", "Case Inbox", "Alerts"]);
    const more = within(bar).getByRole("button", { name: "More" });
    await userEvent.click(more);
    expect(screen.getByRole("dialog", { name: "Main Navigation" })).toBeInTheDocument();
  });

  it("the bottom bar never holds more than three entries, and only the login's own", () => {
    const all = bottomBarFor(makeMe(["cases.view_scope", "cases.view_all", "users.view", "reports.state"], "super_admin"));
    expect(all.length).toBeLessThanOrEqual(3);
    expect(all.map((e) => e.key)).toEqual(["dashboard", "inbox", "alerts"]);
    expect(bottomBarFor(makeMe(["users.view"], "dept_admin")).map((e) => e.key)).toEqual(["dashboard"]);
  });

  it("the breadcrumb renders inside the page header, above the title", () => {
    resetNav("/inbox/sent");
    renderWithClient(<PageHeader title="Case Inbox" />);
    const header = screen.getByRole("banner");
    const crumbs = within(header).getByRole("navigation", { name: "Breadcrumb" });
    const title = within(header).getByRole("heading", { level: 1, name: "Case Inbox" });
    expect(crumbs.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(crumbs).getByText("Sent by Me", { selector: "[aria-current=page]" })).toBeInTheDocument();
  });

  it("the drawer state resets when the window grows past 820 px (review of round 1)", async () => {
    const listeners: ((e: { matches: boolean }) => void)[] = [];
    let wide = false;
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query.includes("min-width") ? wide : false,
        media: query,
        addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.push(cb),
        removeEventListener: vi.fn(),
      })),
    );
    try {
      shellApi();
      renderWithClient(
        <PortalShell>
          <p>page body</p>
        </PortalShell>,
      );
      const open = await screen.findByRole("button", { name: "Open Menu" });
      await userEvent.click(open);
      expect(screen.getByRole("dialog", { name: "Main Navigation" })).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");
      wide = true;
      act(() => listeners.forEach((cb) => cb({ matches: true })));
      expect(open).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("dialog", { name: "Main Navigation" })).toBeNull();
      expect(document.body.style.overflow).toBe("");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("navigation counts (portal-ui-redesign, decision 4; round 2)", () => {
  const CLAIMER: Permission[] = ["cases.view_scope", "cases.claim", "cases.transfer_decide"];
  const claimer = () =>
    makeMe(CLAIMER, "dept_admin", {
      memberships: [
        {
          id: "m-1",
          office: { code: "EDU", name: "Education", kind: "department" },
          department_code: "EDU",
          designation: null,
          role: "dept_admin",
          is_primary: true,
          is_active: true,
          functions: CLAIMER,
        },
        {
          id: "m-2",
          office: { code: "HEALTH", name: "Health", kind: "department" },
          department_code: "HEALTH",
          designation: null,
          role: "dept_admin",
          is_primary: false,
          is_active: true,
          functions: CLAIMER,
        },
      ],
    });

  it("Case inbox shows the Working on count from /inbox/mine/counts, no Cases pill; Case claim the sum over the departments", async () => {
    const block = (code: string, high: number, medium: number, transfers: number | null) => ({
      office_code: code,
      recommended_high: high,
      recommended_medium: medium,
      claimed_active: 0,
      claimed_disposed: 0,
      transfers_in_open: transfers,
      pool_with_hearing_7d: 0,
      whole_department: true,
    });
    browserApi({
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 0, open: { critical: 0, high: 0, normal: 0 } },
      "GET /inbox/mine/counts": { working: 5, files: 2, claimed: 7, disposed: 1 },
      "GET /inbox/counts": { departments: [block("EDU", 2, 1, 1), block("HEALTH", 0, 4, null)] },
    });
    renderWithClient(<Sidebar me={claimer()} />);
    expect(await screen.findByRole("treeitem", { name: "Case Inbox, 5" })).toHaveAttribute("href", "/inbox");
    expect(await screen.findByRole("treeitem", { name: "Case Claim, 8" })).toHaveAttribute("href", "/claim");
    expect(screen.queryByRole("treeitem", { name: /^Cases/ })).toBeNull();
    expect(screen.queryByText("2")).toBeNull();
  });

  it("Case claim is not shown without a claim or transfer function", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    expect(screen.queryByRole("treeitem", { name: /Case Claim/ })).toBeNull();
  });
});

describe("the one-level side menu (design portal-ui-polish-2, decisions 14-19)", () => {
  const ALL: Permission[] = [
    "cases.view_scope",
    "cases.view_all",
    "reports.state",
    "audit.view",
    "admin.data_load",
    "admin.service_health",
    "users.view",
    "offices.manage",
    "access.manage_types",
  ];
  const tree = () => screen.getByRole("navigation", { name: "Main Navigation" });
  const item = (name: string) => within(tree()).getByRole("treeitem", { name });

  /** Clicks and reports whether the menu stopped the browser from following the link. */
  function click(el: HTMLElement): { prevented: boolean } {
    const seen = { prevented: false };
    const after = (e: Event) => {
      seen.prevented = e.defaultPrevented;
      e.preventDefault(); // jsdom cannot navigate; the menu's own decision was read above
    };
    document.addEventListener("click", after);
    fireEvent.click(el);
    document.removeEventListener("click", after);
    return seen;
  }

  function sidebar(path = "/", props: { onNavigate?: () => void } = {}) {
    resetNav(path);
    browserApi({ "GET /reference/labels": labels() });
    return renderWithClient(<Sidebar me={makeMe(ALL, "super_admin")} {...props} />);
  }

  it("a parent toggles aria-expanded and opening one closes the other", () => {
    sidebar("/");
    const admin = item("Administration");
    const reports = item("Reports");
    expect(admin).toHaveAttribute("aria-expanded", "false");
    click(admin);
    expect(admin).toHaveAttribute("aria-expanded", "true");
    expect(within(tree()).getByRole("group", { name: "Administration" })).toBeInTheDocument();
    click(reports);
    expect(reports).toHaveAttribute("aria-expanded", "true");
    expect(admin).toHaveAttribute("aria-expanded", "false");
  });

  it("a closed parent goes to its landing page; an open one closes without navigating", () => {
    sidebar("/");
    const data = item("Data Collection");
    expect(data).toHaveAttribute("href", "/data/load");
    expect(click(data).prevented).toBe(false);
    expect(data).toHaveAttribute("aria-expanded", "true");
    expect(click(data).prevented).toBe(true);
    expect(data).toHaveAttribute("aria-expanded", "false");
  });

  it("already on one of its pages, clicking the closed parent opens it without navigating", () => {
    sidebar("/admin/offices");
    const admin = item("Administration");
    click(admin); // open on the path: closes
    expect(admin).toHaveAttribute("aria-expanded", "false");
    expect(click(admin).prevented).toBe(true);
    expect(admin).toHaveAttribute("aria-expanded", "true");
  });

  it("the active child is the page, its parent is on the path, and a route change opens the new parent", () => {
    const { rerender, client } = sidebar("/admin/offices");
    const admin = item("Administration");
    expect(admin).toHaveAttribute("aria-expanded", "true");
    expect(admin.className).toMatch(/onPath/);
    expect(item("Offices")).toHaveAttribute("aria-current", "page");
    expect(item("Users")).not.toHaveAttribute("aria-current");
    nav.pathname = "/reports/data-health";
    rerender(
      <QueryClientProvider client={client}>
        <Sidebar me={makeMe(ALL, "super_admin")} />
      </QueryClientProvider>,
    );
    expect(item("Reports")).toHaveAttribute("aria-expanded", "true");
    expect(item("Administration")).toHaveAttribute("aria-expanded", "false");
    expect(item("Data Collection Health")).toHaveAttribute("aria-current", "page");
  });

  it("closed children are neither focusable nor read", () => {
    sidebar("/");
    const admin = item("Administration");
    const group = document.getElementById(admin.getAttribute("aria-owns")!)!;
    const wrapper = group.parentElement!;
    expect(wrapper).toHaveAttribute("inert");
    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    for (const link of within(group).getAllByRole("treeitem", { hidden: true })) expect(link).toHaveAttribute("tabindex", "-1");
    click(admin);
    expect(wrapper).not.toHaveAttribute("inert");
    expect(wrapper).not.toHaveAttribute("aria-hidden");
  });

  it("one tab stop for the whole menu; the arrows, Home, End, Right and Left move across groups", async () => {
    sidebar("/");
    const stops = () => tree().querySelectorAll('[role="treeitem"][tabindex="0"]');
    expect(stops()).toHaveLength(1);
    expect(stops()[0]).toHaveTextContent("Dashboard");
    const user = userEvent.setup();
    // Tab from the drawer's search box enters the menu once, on its one stop
    document.getElementById("drawer-search")!.focus();
    for (let i = 0; i < 3 && !tree().contains(document.activeElement); i++) await user.tab();
    expect(document.activeElement).toHaveTextContent("Dashboard");
    await user.keyboard("{End}");
    expect(document.activeElement).toHaveTextContent("Administration");
    expect(stops()).toHaveLength(1);
    await user.keyboard("{ArrowRight}");
    expect(item("Administration")).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toHaveTextContent("Users");
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toHaveTextContent("User Types");
    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement).toHaveTextContent("Administration");
    await user.keyboard("{ArrowLeft}");
    expect(item("Administration")).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{ArrowUp}");
    expect(document.activeElement).toHaveTextContent("System Health");
    // across the group boundary: from the first Settings row up into Oversight
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(document.activeElement).toHaveTextContent("Audit Log");
    await user.keyboard("{Home}");
    expect(document.activeElement).toHaveTextContent("Dashboard");
    expect(stops()).toHaveLength(1);
    // and leaves it once
    await user.tab();
    expect(tree().contains(document.activeElement)).toBe(false);
    await user.tab({ shift: true });
    expect(document.activeElement).toHaveTextContent("Dashboard");
    // Enter on a parent acts as a click: it opens
    await user.keyboard("{End}");
    const after = (e: Event) => e.preventDefault();
    document.addEventListener("click", after);
    await user.keyboard("{Enter}");
    document.removeEventListener("click", after);
    expect(item("Administration")).toHaveAttribute("aria-expanded", "true");
  });

  it("a truncated label gets its full text as the title, and only then", () => {
    sidebar("/");
    const reports = item("Reports");
    const label = reports.querySelector<HTMLElement>("[data-nav-label]")!;
    Object.defineProperty(label, "clientWidth", { configurable: true, value: 100 });
    Object.defineProperty(label, "scrollWidth", { configurable: true, value: 100 });
    fireEvent.pointerEnter(reports);
    expect(reports).not.toHaveAttribute("title");
    Object.defineProperty(label, "scrollWidth", { configurable: true, value: 180 });
    fireEvent.focus(reports);
    expect(reports).toHaveAttribute("title", "Reports");
    expect(reports).toHaveAccessibleName("Reports");
  });

  it("under reduced motion the open state applies at once (the CSS tokens are 0 ms; nothing waits in script)", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("reduce"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    sidebar("/");
    const admin = item("Administration");
    click(admin);
    const wrapper = document.getElementById(admin.getAttribute("aria-owns")!)!.parentElement!;
    expect(wrapper).toHaveAttribute("data-open", "true");
    expect(within(wrapper).getByRole("treeitem", { name: "Users" })).toBeVisible();
  });

  it("in the drawer, choosing a child closes it and toggling a parent does not", () => {
    const onNavigate = vi.fn();
    sidebar("/", { onNavigate });
    click(item("Administration"));
    expect(onNavigate).not.toHaveBeenCalled();
    click(item("Users"));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    click(item("Search"));
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });

  it("the count pills stay on Case Inbox, Case Claim and Alerts", async () => {
    resetNav("/");
    browserApi({
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 4, open: { critical: 0, high: 0, normal: 4 } },
      "GET /inbox/mine/counts": { working: 2, files: 0, claimed: 0, disposed: 0 },
    });
    renderWithClient(<Sidebar me={makeMe(["cases.view_scope"])} />);
    expect(await screen.findByRole("treeitem", { name: "Alerts, 4" })).toBeInTheDocument();
    expect(await screen.findByRole("treeitem", { name: "Case Inbox, 2" })).toBeInTheDocument();
  });
});

import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("Work lists Cause list, Files, Alerts & calendar and Search in order for a case reader (portal-ui-redesign)", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const names = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(names).toEqual(["Dashboard", "Case inbox", "Cause list", "Files", "Alerts & calendar", "Search"]);
    expect(within(nav).getByRole("link", { name: "Cause list" })).toHaveAttribute("href", "/causelist");
    expect(within(nav).getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
    expect(within(nav).getByRole("link", { name: "Alerts & calendar" })).toHaveAttribute("href", "/alerts");
  });

  it("Reports and Audit log sit under Oversight, Data collection and Administration under Settings", () => {
    browserApi({ "GET /reference/labels": labels() });
    const me = makeMe(["cases.view_all", "reports.state", "audit.view", "users.view"], "super_admin");
    renderWithClient(<Sidebar me={me} />);
    const oversight = screen.getByRole("list", { name: "Oversight" });
    expect(
      within(oversight)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Reports", "Audit log"]);
    const settings = screen.getByRole("list", { name: "Settings" });
    expect(
      within(settings)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Data collection", "Administration"]);
    expect(within(screen.getByRole("list", { name: "Work" })).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("a group with no visible entry is hidden", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    expect(screen.getByRole("list", { name: "Work" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Oversight" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Settings" })).toBeNull();
    expect(screen.queryByText("Oversight")).toBeNull();
  });

  it("the Alerts entry shows the unread count from /alerts/counts in its pill", async () => {
    browserApi({
      "GET /reference/labels": labels(),
      "GET /alerts/counts": { unread: 3, open: { critical: 0, high: 1, normal: 2 } },
    });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const link = await screen.findByRole("link", { name: "Alerts & calendar, 3" });
    expect(link).toHaveAttribute("href", "/alerts");
    expect(within(link).getByText("3")).toHaveAttribute("aria-hidden", "true");
  });

  it("Reports shows with a reports function, before Data collection (portal-reports)", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["cases.view_all", "reports.state"], "state_oversight")} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const names = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(names.indexOf("Data collection")).toBe(names.indexOf("Reports") + 1);
    expect(within(nav).getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");
  });

  it("Files stays current across its tabs", () => {
    resetNav("/files/sent");
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Files" })).toHaveAttribute("aria-current", "page");
  });

  it("an officer sees no Administration and no unbuilt entries", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByRole("link", { name: "Administration" })).toBeNull();
    for (const unbuilt of ["Reports", "Audit log", "Data collection"]) {
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
    expect(await mappingTabs(["admin.keywords"])).toEqual(["Keywords and name patterns", "Court search", "Scoring"]);
  });

  it("every tab for the super admin's functions", async () => {
    expect(await mappingTabs(["admin.counsel_codes", "admin.keywords", "admin.watchlist", "admin.scoring"])).toEqual([
      "Counsel codes",
      "Keywords and name patterns",
      "Court search",
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

  it("the breadcrumb names the Files and Alerts screens by path, the case tab by segment", () => {
    for (const [path, last] of [
      ["/files/offices", "My offices"],
      ["/files/mine", "With me"],
      ["/alerts", "Alerts & calendar"],
      ["/alerts/calendar", "Hearing calendar"],
      ["/cases/EDU-2026-0001/alerts", "Alerts"],
      ["/admin/offices", "Offices"],
      ["/reports/pending-cases", "Pending cases"],
      ["/reports/data-health", "Data collection health"],
    ] as const) {
      resetNav(path);
      const { unmount } = renderWithClient(<Breadcrumb />);
      const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
      expect(within(crumbs).getByText(last, { selector: "[aria-current=page]" })).toBeInTheDocument();
      unmount();
    }
    resetNav("/files/offices");
    renderWithClient(<Breadcrumb />);
    expect(screen.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
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
    expect(slot).toHaveAttribute("title", "Place for the official Government of Assam emblem");
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
    expect(within(header).getByRole("button", { name: "User menu" })).toHaveTextContent("AS");
    expect(within(header).queryByRole("navigation", { name: "Breadcrumb" })).toBeNull();
  });

  it("the avatar menu opens and closes by keyboard and lists My profile and Sign out", async () => {
    shellApi();
    renderWithClient(
      <PortalShell>
        <p>page body</p>
      </PortalShell>,
    );
    const button = await screen.findByRole("button", { name: "User menu" });
    button.focus();
    await userEvent.keyboard("{ArrowDown}");
    const menu = screen.getByRole("menu", { name: "User menu" });
    expect(within(menu).getByRole("menuitem", { name: "My profile" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Sign out" })).toHaveFocus();
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
    const open = await screen.findByRole("button", { name: "Open menu" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    const drawer = screen.getByRole("dialog", { name: "Main navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(drawer.contains(document.activeElement)).toBe(true);
    // Tab past the last control comes back to the first: the focus stays in the drawer
    for (let i = 0; i < 20; i += 1) await userEvent.tab();
    expect(drawer.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Main navigation" })).toBeNull();
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
    const bar = await screen.findByRole("navigation", { name: "Quick links" });
    expect(
      within(bar)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Dashboard", "Case inbox", "Files"]);
    const more = within(bar).getByRole("button", { name: "More" });
    await userEvent.click(more);
    expect(screen.getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("the bottom bar never holds more than three entries, and only the login's own", () => {
    const all = bottomBarFor(makeMe(["cases.view_scope", "cases.view_all", "users.view", "reports.state"], "super_admin"));
    expect(all.length).toBeLessThanOrEqual(3);
    expect(all.map((e) => e.key)).toEqual(["dashboard", "inbox", "files"]);
    expect(bottomBarFor(makeMe(["users.view"], "dept_admin")).map((e) => e.key)).toEqual(["dashboard"]);
  });

  it("the breadcrumb renders inside the page header, above the title", () => {
    resetNav("/files/offices");
    renderWithClient(<PageHeader title="Files" />);
    const header = screen.getByRole("banner");
    const crumbs = within(header).getByRole("navigation", { name: "Breadcrumb" });
    const title = within(header).getByRole("heading", { level: 1, name: "Files" });
    expect(crumbs.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(crumbs).getByText("My offices", { selector: "[aria-current=page]" })).toBeInTheDocument();
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
      const open = await screen.findByRole("button", { name: "Open menu" });
      await userEvent.click(open);
      expect(screen.getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");
      wide = true;
      act(() => listeners.forEach((cb) => cb({ matches: true })));
      expect(open).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("dialog", { name: "Main navigation" })).toBeNull();
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

  it("Case inbox and Files show their counts from /inbox/mine/counts; Case claim the sum over the departments", async () => {
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
    expect(await screen.findByRole("link", { name: "Case inbox, 5" })).toHaveAttribute("href", "/inbox");
    expect(await screen.findByRole("link", { name: "Files, 2" })).toHaveAttribute("href", "/files");
    expect(await screen.findByRole("link", { name: "Case claim, 8" })).toHaveAttribute("href", "/claim");
  });

  it("Case claim is not shown without a claim or transfer function", () => {
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(OFFICER)} />);
    expect(screen.queryByRole("link", { name: /Case claim/ })).toBeNull();
  });
});

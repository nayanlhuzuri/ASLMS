import { describe, expect, it } from "vitest";

import type { Permission, Role } from "./api/types";
import { readsAudit, tracksDepartment } from "./can";
import {
  ADMIN_FUNCTIONS,
  ADMIN_TABS,
  adminTabsFor,
  alertsTabsFor,
  AUDIT_ENTRY_CRUMB,
  CASE_TABS,
  BOTTOM_BAR_KEYS,
  CASES_LIST_SEGMENTS,
  CRUMB_PATHS,
  crumbLabel,
  CRUMBS,
  DATA_TABS,
  dataTabsFor,
  inboxTabsFor,
  MAPPING_FUNCTIONS,
  MAPPING_TABS,
  mappingTabsFor,
  NAV,
  navFor,
  OLD_CASES_REDIRECTS,
  OLD_FILES_REDIRECTS,
  PEOPLE_ADMIN_FUNCTIONS,
} from "./routes";

const only = (fn: Permission) => ({ functions: [fn] });
const keys = (tabs: { key: string }[]) => tabs.map((t) => t.key);

describe("department mapping navigation", () => {
  it("Administration shows with any of the four mapping functions", () => {
    for (const fn of ["admin.counsel_codes", "admin.keywords", "admin.watchlist", "admin.scoring"] as const) {
      expect(ADMIN_FUNCTIONS).toContain(fn);
    }
    expect(ADMIN_FUNCTIONS).toEqual([...PEOPLE_ADMIN_FUNCTIONS, ...MAPPING_FUNCTIONS]);
  });

  it("Designations keeps exactly the people and offices functions", () => {
    const designations = ADMIN_TABS.find((t) => t.key === "designations")!;
    expect(designations.functions).toEqual(PEOPLE_ADMIN_FUNCTIONS);
    expect(PEOPLE_ADMIN_FUNCTIONS).toHaveLength(6);
    expect(keys(adminTabsFor(only("admin.watchlist")))).toEqual(["mapping"]);
  });

  it("the mapping tab follows the mapping functions", () => {
    const mapping = ADMIN_TABS.find((t) => t.key === "mapping")!;
    expect(mapping.href).toBe("/admin/mapping");
    expect(mapping.functions).toEqual(MAPPING_FUNCTIONS);
    expect(keys(adminTabsFor(only("users.view")))).not.toContain("mapping");
  });

  it("each mapping function alone opens its tabs (Scoring by the API's read rule)", () => {
    expect(keys(mappingTabsFor(only("admin.counsel_codes")))).toEqual(["codes", "scoring"]);
    expect(keys(mappingTabsFor(only("admin.keywords")))).toEqual(["keywords", "discovery", "scoring"]);
    expect(keys(mappingTabsFor(only("admin.watchlist")))).toEqual(["watchlist"]);
    expect(keys(mappingTabsFor(only("admin.scoring")))).toEqual(["scoring"]);
    expect(mappingTabsFor(only("users.view"))).toEqual([]);
    expect(mappingTabsFor(null)).toEqual([]);
  });
});

describe("department discovery navigation", () => {
  it("the Court search tab follows admin.keywords and the Discovery data tab the data readers", () => {
    const court = MAPPING_TABS.find((t) => t.key === "discovery")!;
    expect(court.href).toBe("/admin/mapping/discovery");
    expect(court.functions).toEqual(["admin.keywords"]);
    expect(keys(mappingTabsFor(only("admin.counsel_codes")))).not.toContain("discovery");
    const data = DATA_TABS.find((t) => t.key === "discovery")!;
    expect(data.href).toBe("/data/discovery");
    for (const fn of ["admin.data_load", "reports.state", "admin.napix_refetch", "admin.masters_sync"] as const) {
      expect(keys(dataTabsFor(only(fn)))).toContain("discovery");
    }
    expect(keys(dataTabsFor(only("admin.keywords")))).not.toContain("discovery");
    expect(crumbLabel("/admin/mapping/discovery")).toBe("Court Search");
    expect(crumbLabel("/data/discovery")).toBe("Discovery");
  });
});

describe("the case page tabs (portal-workflow)", () => {
  it("six tabs and the Assistant, then Parties, Linked cases, Journey and stage, Alerts and Details under More (portal-ui-redesign, 10.9; assistant, 14; case-workspace-admin, open question 3)", () => {
    expect(CASE_TABS.filter((t) => !t.more).map((t) => t.label)).toEqual([
      "Overview",
      "Hearings",
      "Orders",
      "Documents",
      "Notes",
      "Timeline",
      "Assistant", // shown only with assistant.use while the assistant is on (CaseFrame)
    ]);
    expect(CASE_TABS.filter((t) => t.more).map((t) => t.key)).toEqual(["parties", "links", "custody", "alerts", "details"]);
    expect(CASE_TABS.find((t) => t.key === "custody")!.label).toBe("Journey and Stage");
    expect(CASE_TABS.find((t) => t.key === "alerts")!.count).toBeNull();
    expect(CRUMBS.custody).toBe("Journey and Stage");
    expect(CRUMBS.alerts).toBe("Alerts");
  });

});

const membership = (department_code: string | null, functions: Permission[], role: Role = "dept_admin") => ({
  id: `m-${department_code ?? "state"}`,
  office: { code: department_code ?? "GOA", name: department_code ?? "Assam", kind: department_code ? "department" : "state" },
  department_code,
  designation: null,
  role,
  is_primary: true,
  is_active: true,
  functions,
});

describe("Files, My calendar and Alerts navigation (portal-files-alerts; portal-ui-redesign, decision 8)", () => {
  it("Alerts and My calendar show for case readers", () => {
    expect(navFor({ functions: ["cases.view_scope"] }).find((e) => e.key === "alerts")!.label).toBe("Alerts");
    expect(navFor({ functions: ["cases.view_scope"] }).find((e) => e.key === "calendar")!.href).toBe("/calendar");
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("calendar");
    expect(navFor({ functions: ["cases.view_scope"] }).map((e) => e.key)).toContain("alerts");
    expect(navFor({ functions: ["cases.view_all"] }).map((e) => e.key)).toContain("alerts");
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("alerts");
  });

  it("one Case inbox entry and no Cases entry; it shows for a standing counsel without a department (case-inbox-merge, decision 6)", () => {
    expect(NAV.map((e) => e.key)).not.toContain("files");
    const reader = navFor({ functions: ["cases.view_scope"], memberships: [] });
    expect(reader.map((e) => e.key)).not.toContain("files");
    const counsel = navFor({
      functions: ["cases.view_scope"],
      memberships: [{ ...membership(null, ["cases.view_scope"], "standing_counsel"), office: { code: "AG", name: "Advocate General", kind: "office" } }],
    });
    const inbox = counsel.find((e) => e.key === "inbox")!;
    expect(inbox.label).toBe("Case Inbox");
    expect(inbox.href).toBe("/inbox");
    expect(inbox.count).toBe("inbox");
    expect(counsel.map((e) => e.key)).not.toContain("claim");
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("inbox");
  });

  it("the phone bottom bar is Dashboard, Case inbox and Alerts (case-inbox-merge, decision 14)", () => {
    expect(BOTTOM_BAR_KEYS).toEqual(["dashboard", "inbox", "alerts"]);
  });

  it("the Case inbox tabs per login (case-inbox-merge, decision 7)", () => {
    const officer = { functions: ["cases.view_scope"] as Permission[], memberships: [membership("EDU", ["cases.view_scope"], "dept_officer")] };
    expect(keys(inboxTabsFor(officer))).toEqual(["working", "sent", "disposed"]);
    const claimer = {
      functions: ["cases.view_scope", "cases.claim"] as Permission[],
      memberships: [membership("EDU", ["cases.view_scope", "cases.claim"], "dept_officer")],
    };
    expect(keys(inboxTabsFor(claimer))).toEqual(["working", "sent", "claimed", "disposed"]);
    const headFns: Permission[] = ["cases.view_scope", "cases.claim", "cases.allot", "custody.track"];
    const head = { functions: headFns, memberships: [membership("EDU", headFns)] };
    const all = inboxTabsFor(head, { whole: true });
    expect(keys(all)).toEqual(["working", "sent", "claimed", "disposed", "department", "pending"]);
    expect(all.map((t) => t.label)).toEqual(["Working On", "Sent by Me", "Claimed by Me", "Disposed", "Department Cases", "Pending Action"]);
    expect(all.map((t) => t.href)).toEqual([
      "/inbox/working",
      "/inbox/sent",
      "/inbox/claimed-by-me",
      "/inbox/disposed",
      "/inbox/department",
      "/inbox/pending",
    ]);
    expect(tracksDepartment(head)).toBe(true);
    // State oversight: Department cases, no Pending action (its State membership has no department)
    const state = {
      functions: ["cases.view_scope", "cases.view_all", "custody.track"] as Permission[],
      memberships: [membership(null, ["cases.view_scope", "cases.view_all", "custody.track"], "state_oversight")],
    };
    expect(keys(inboxTabsFor(state))).toEqual(["working", "sent", "disposed", "department"]);
    expect(inboxTabsFor(null)).toEqual([]);
  });

  it("no case reference can equal a Cases list segment (decision 3)", () => {
    expect(CASES_LIST_SEGMENTS).toEqual(["with-me", "sent", "pending"]);
    // a ref_no in the dash form starts with letters and a year (CASE-2026-000001), a CNR is 16 characters of letters
    // and digits, an id is a UUID: none is a lower-case word with a dash and no digit
    const refs = ["CASE-2026-000001", "ASGH010012342026", "0192f0e4-5b7a-7c3d-9e1f-123456789abc"];
    for (const seg of CASES_LIST_SEGMENTS) {
      expect(/[0-9]/.test(seg)).toBe(false);
      expect(refs).not.toContain(seg);
      expect(seg).toMatch(/^[a-z]+(-[a-z]+)?$/);
    }
  });

  it("the old Files and Cases list addresses lead to the Case inbox tabs (case-inbox-merge, decision 12)", () => {
    expect(OLD_FILES_REDIRECTS).toEqual({
      "/files": "/inbox/working",
      "/files/mine": "/inbox/working",
      "/files/offices": "/inbox/working?held=offices",
      "/files/department": "/inbox/pending",
      "/files/sent": "/inbox/sent",
      "/inbox/files": "/inbox/working",
    });
    expect(OLD_CASES_REDIRECTS).toEqual({
      "/cases/with-me": "/inbox/working",
      "/cases/sent": "/inbox/sent",
      "/cases/pending": "/inbox/pending",
    });
  });

  it("the Alerts frame has the alerts tab for case readers (the calendar moved to My calendar)", () => {
    expect(keys(alertsTabsFor({ functions: ["cases.view_scope"] }))).toEqual(["list"]);
    expect(alertsTabsFor({ functions: ["users.view"] })).toEqual([]);
  });

  it("the Next dates to confirm tab shows only with next_dates.review (portal-next-dates, decision 1)", () => {
    const both = alertsTabsFor({ functions: ["cases.view_scope", "next_dates.review"] });
    expect(keys(both)).toEqual(["list", "next-dates"]);
    expect(both[1]!.label).toBe("Next Dates to Confirm");
    expect(both[1]!.href).toBe("/alerts/next-dates");
    expect(keys(alertsTabsFor({ functions: ["cases.view_scope"] }))).not.toContain("next-dates");
    expect(crumbLabel("/alerts/next-dates")).toBe("Next Dates to Confirm");
  });

  it("CRUMB_PATHS names the screens by path, while the segments keep their meaning", () => {
    expect(crumbLabel("/inbox/sent")).toBe("Sent by Me");
    expect(crumbLabel("/inbox/pending")).toBe("Pending Action");
    expect(crumbLabel("/inbox/working")).toBe("Working On");
    expect(CRUMB_PATHS["/cases/with-me"]).toBeUndefined();
    expect(crumbLabel("/admin/offices")).toBe("Offices");
    expect(crumbLabel("/alerts")).toBe("Alerts");
    expect(crumbLabel("/calendar")).toBe("My Calendar");
    expect(crumbLabel("/cases/x/alerts")).toBe("Alerts");
    expect(crumbLabel("/alerts/calendar")).toBe("Hearing Calendar");
    // the crumb above a case page leads to the Case inbox (case-inbox-merge, decision 12)
    expect(CRUMB_PATHS["/cases"]).toBe("Case Inbox");
    expect(crumbLabel("/cases")).toBe("Case Inbox");
  });
});

describe("the Cause list navigation (portal-causelist)", () => {
  it("shows for cases.view_scope and for cases.view_all, in Work before Search, and not without them", () => {
    // portal-ui-redesign, decision 4: Dashboard, Case inbox, Case claim, Cause list, Files, My calendar, Alerts, Search
    for (const fn of ["cases.view_scope", "cases.view_all"] as const) {
      const keys = navFor({ functions: [fn], memberships: [] }).map((e) => e.key);
      expect(keys).toContain("causelist");
      expect(keys.indexOf("causelist")).toBeLessThan(keys.indexOf("search"));
      expect(NAV.find((e) => e.key === "causelist")!.group).toBe("work");
    }
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("causelist");
    expect(navFor({ functions: [] }).map((e) => e.key)).not.toContain("causelist");
    const entry = navFor({ functions: ["cases.view_scope"] }).find((e) => e.key === "causelist")!;
    expect(entry.label).toBe("Cause List");
    expect(entry.href).toBe("/causelist");
  });
});

describe("Reports navigation (portal-reports)", () => {
  it("the entry is built and shows with either reports function", () => {
    expect(navFor(only("reports.department")).map((e) => e.key)).toContain("reports");
    expect(navFor(only("reports.state")).map((e) => e.key)).toContain("reports");
    expect(navFor(only("cases.view_scope")).map((e) => e.key)).not.toContain("reports");
  });

  it("names the four tabs in the breadcrumb", () => {
    expect(CRUMBS.reports).toBe("Reports");
    expect(crumbLabel("/reports")).toBe("Reports");
    expect(CRUMB_PATHS["/reports/hearings-disposals"]).toBe("Hearings and Disposals");
    expect(crumbLabel("/reports/pending-actions")).toBe("Pending Actions");
  });
});

describe("Audit log navigation (portal-audit-health)", () => {
  type M = { role: Role; functions: Permission[]; is_active?: boolean; department_code?: string | null };
  const me = (memberships: M[]) => {
    const all = [...new Set(memberships.filter((m) => m.is_active !== false).flatMap((m) => m.functions))];
    return {
      functions: all,
      memberships: memberships.map((m, i) => ({
        id: `m-${i}`,
        office: { code: "X", name: "X", kind: "department" },
        department_code: m.department_code ?? null,
        designation: null,
        is_primary: i === 0,
        is_active: m.is_active ?? true,
        role: m.role,
        functions: m.functions,
      })),
    } as unknown as Parameters<typeof readsAudit>[0];
  };
  const superAdmin = me([{ role: "super_admin", functions: ["audit.view", "cases.view_all", "users.view"] }]);
  const auditor = me([{ role: "auditor", functions: ["audit.view", "cases.view_all"] }]);
  const deptOnly = me([{ role: "dept_admin", functions: ["audit.view", "cases.view_scope"], department_code: "EDU" }]);
  const split = me([
    { role: "dept_admin", functions: ["audit.view"], department_code: "EDU" },
    { role: "state_oversight", functions: ["cases.view_all"] },
  ]);
  const inactive = me([
    { role: "auditor", functions: ["audit.view", "cases.view_all"], is_active: false },
    { role: "dept_officer", functions: ["cases.view_scope"], department_code: "EDU" },
  ]);

  it("readsAudit: the super admin and the Auditor only", () => {
    expect(readsAudit(superAdmin)).toBe(true);
    expect(readsAudit(auditor)).toBe(true);
    expect(readsAudit(deptOnly)).toBe(false);
    expect(readsAudit(split)).toBe(false);
    expect(readsAudit(inactive)).toBe(false);
    expect(readsAudit(null)).toBe(false);
  });

  it("the entry is built and shows only where the API serves the log", () => {
    const keys = (m: Parameters<typeof navFor>[0]) => navFor(m).map((e) => e.key);
    expect(keys(superAdmin as Parameters<typeof navFor>[0])).toContain("audit");
    expect(keys(auditor as Parameters<typeof navFor>[0])).toContain("audit");
    expect(keys(deptOnly as Parameters<typeof navFor>[0])).not.toContain("audit");
    expect(keys(split as Parameters<typeof navFor>[0])).not.toContain("audit");
    const order = NAV.map((e) => e.key);
    expect(order.indexOf("audit")).toBe(order.indexOf("reports") + 1);
    expect(order.indexOf("data")).toBe(order.indexOf("audit") + 1);
  });

  it("names the screen and an entry in the breadcrumb", () => {
    expect(CRUMBS.audit).toBe("Audit Log");
    expect(crumbLabel("/audit")).toBe("Audit Log");
    expect(crumbLabel("/audit/0192a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b")).toBe(AUDIT_ENTRY_CRUMB);
    expect(AUDIT_ENTRY_CRUMB).toBe("Entry");
  });
});

describe("System health navigation (api-health-checker, decision 2)", () => {
  it("the entry shows only with admin.service_health, in Settings after Data collection", () => {
    const entry = NAV.find((e) => e.key === "system")!;
    expect(entry).toMatchObject({ href: "/system", group: "settings", label: "System Health", functions: ["admin.service_health"] });
    expect(navFor({ functions: ["admin.service_health"] }).map((e) => e.key)).toEqual(["dashboard", "system"]);
    for (const fn of ["admin.napix_refetch", "admin.masters_sync", "reports.state", "admin.data_load"] as const) {
      expect(navFor(only(fn)).map((e) => e.key)).not.toContain("system");
    }
    const keys = NAV.map((e) => e.key);
    expect(keys.indexOf("system")).toBe(keys.indexOf("data") + 1);
    expect(keys.indexOf("admin")).toBe(keys.indexOf("system") + 1);
    expect(crumbLabel("/system")).toBe("System Health");
  });
});

describe("the one-level menu (design portal-ui-polish-2, decisions 14 and 15)", () => {
  const entry = (functions: Permission[], key: string) => navFor({ functions }).find((e) => e.key === key);
  const keys = (functions: Permission[], key: string) => entry(functions, key)?.children?.map((c) => c.key);

  it("four entries expand, each to its own pages; every other entry is a plain link", () => {
    const all = NAV.filter((e) => e.children).map((e) => e.key);
    expect(all).toEqual(["reports", "data", "system", "admin"]);
    expect(keys(["users.view", "access.manage_types", "offices.manage", "admin.designations", "admin.keywords", "admin.tickets"], "admin")).toEqual(
      ["users", "access", "offices", "designations", "mapping", "tickets"],
    );
    expect(keys(["admin.data_load"], "data")).toEqual(["load", "health", "queue", "duplicates", "discovery"]);
    expect(keys(["reports.state"], "reports")).toEqual(["pending-cases", "hearings-disposals", "pending-actions", "data-health"]);
    expect(keys(["admin.service_health"], "system")).toEqual(["court", "services", "token"]);
    for (const e of navFor({ functions: ["cases.view_scope", "cases.view_all", "cases.claim", "audit.view"] })) {
      if (!["reports", "data", "system", "admin"].includes(e.key)) expect(e.children, e.key).toBeUndefined();
    }
  });

  it("Data Health shows only with reports.state", () => {
    expect(keys(["reports.department"], "reports")).toEqual(["pending-cases", "hearings-disposals", "pending-actions"]);
    expect(keys(["reports.state"], "reports")).toContain("data-health");
  });

  it("Administration's children follow ADMIN_TABS' functions", () => {
    expect(keys(["admin.watchlist"], "admin")).toEqual(["mapping"]);
    expect(keys(["users.propose_head"], "admin")).toEqual(["designations", "tickets"]);
    const children = NAV.find((e) => e.key === "admin")!.children!;
    expect(children.map((c) => [c.key, c.href, c.functions])).toEqual(ADMIN_TABS.map((t) => [t.key, t.href, t.functions]));
  });

  it("an entry whose children are all hidden is a plain link", async () => {
    const { filterNav } = await import("./routes");
    const parent = {
      key: "x",
      label: "X",
      href: "/x",
      group: "settings" as const,
      functions: ["users.view"] as Permission[],
      built: true,
      children: [{ key: "a", label: "A", href: "/x/a", functions: ["offices.manage"] as Permission[] }],
    };
    const [plain] = filterNav([parent], { functions: ["users.view"] });
    expect(plain).toBeDefined();
    expect(plain!.children).toBeUndefined();
    expect(plain!.href).toBe("/x");
    const [full] = filterNav([parent], { functions: ["users.view", "offices.manage"] });
    expect(full!.children?.map((c) => c.key)).toEqual(["a"]);
  });

  it("no child has children (one level)", () => {
    for (const e of NAV) for (const c of e.children ?? []) expect("children" in c, `${e.key}/${c.key}`).toBe(false);
  });

  it("the /system children match by hash and by the api key", async () => {
    const { childActive, SYSTEM_SECTIONS } = await import("./routes");
    const [court, services, token] = SYSTEM_SECTIONS;
    expect(childActive(court!, { pathname: "/system", hash: "#court" })).toBe(true);
    expect(childActive(court!, { pathname: "/system", hash: "#services" })).toBe(false);
    expect(childActive(services!, { pathname: "/system", hash: "#services" })).toBe(true);
    expect(childActive(token!, { pathname: "/system", search: "?api=token&tab=token" })).toBe(true);
    expect(childActive(court!, { pathname: "/system", hash: "#court", search: "?api=token" })).toBe(false);
    expect(childActive(token!, { pathname: "/system", hash: "" })).toBe(false);
    expect(token!.href).toBe("/system?api=token&tab=token");
  });

  it("a child is active when the path starts with its href; its parent is then on the path", async () => {
    const { activeChild, onPath } = await import("./routes");
    const admin = entry(["users.view", "offices.manage"], "admin")!;
    expect(activeChild(admin, { pathname: "/admin/offices/EDU" })).toBe("offices");
    expect(onPath(admin, { pathname: "/admin/offices/EDU" })).toBe(true);
    expect(onPath(admin, { pathname: "/inbox" })).toBe(false);
  });
});

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
  CRUMB_PATHS,
  crumbLabel,
  CRUMBS,
  DATA_TABS,
  dataTabsFor,
  filesTabsFor,
  MAPPING_FUNCTIONS,
  MAPPING_TABS,
  mappingTabsFor,
  NAV,
  navFor,
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
    expect(crumbLabel("/admin/mapping/discovery")).toBe("Court search");
    expect(crumbLabel("/data/discovery")).toBe("Discovery");
  });
});

describe("the case page tabs (portal-workflow)", () => {
  it("six tabs and the Assistant, then Parties, Linked cases, Custody and stage, Alerts and Details under More (portal-ui-redesign, 10.9; assistant, 14)", () => {
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
    expect(CASE_TABS.find((t) => t.key === "custody")!.label).toBe("Custody and stage");
    expect(CASE_TABS.find((t) => t.key === "alerts")!.count).toBeNull();
    expect(CRUMBS.custody).toBe("Custody and stage");
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

  it("Files shows with cases.view_scope, after Search and Cause list", () => {
    const keys = navFor({ functions: ["cases.view_scope"], memberships: [] }).map((e) => e.key);
    expect(keys.indexOf("files")).toBe(keys.indexOf("causelist") + 1);
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("files");
  });

  it("the Department files tab needs a department membership holding custody.track", () => {
    const officer = { functions: ["cases.view_scope"] as Permission[], memberships: [membership("EDU", ["cases.view_scope"])] };
    expect(keys(filesTabsFor(officer))).toEqual(["mine", "offices", "sent"]);
    const tracker = {
      functions: ["cases.view_scope", "custody.track"] as Permission[],
      memberships: [membership("EDU", ["cases.view_scope", "custody.track"])],
    };
    expect(keys(filesTabsFor(tracker))).toEqual(["mine", "offices", "department", "sent"]);
    expect(tracksDepartment(tracker)).toBe(true);
    // the super admin's State membership has no department: no Department files tab
    const root = {
      functions: ["cases.view_scope", "cases.view_all", "custody.track"] as Permission[],
      memberships: [membership(null, ["cases.view_scope", "cases.view_all", "custody.track"], "super_admin")],
    };
    expect(keys(filesTabsFor(root))).toEqual(["mine", "offices", "sent"]);
    expect(filesTabsFor(null)).toEqual([]);
  });

  it("the Alerts frame has the alerts tab for case readers (the calendar moved to My calendar)", () => {
    expect(keys(alertsTabsFor({ functions: ["cases.view_scope"] }))).toEqual(["list"]);
    expect(alertsTabsFor({ functions: ["users.view"] })).toEqual([]);
  });

  it("the Next dates to confirm tab shows only with next_dates.review (portal-next-dates, decision 1)", () => {
    const both = alertsTabsFor({ functions: ["cases.view_scope", "next_dates.review"] });
    expect(keys(both)).toEqual(["list", "next-dates"]);
    expect(both[1]!.label).toBe("Next dates to confirm");
    expect(both[1]!.href).toBe("/alerts/next-dates");
    expect(keys(alertsTabsFor({ functions: ["cases.view_scope"] }))).not.toContain("next-dates");
    expect(crumbLabel("/alerts/next-dates")).toBe("Next dates to confirm");
  });

  it("CRUMB_PATHS names the screens by path, while the segments keep their meaning", () => {
    expect(crumbLabel("/files/offices")).toBe("My offices");
    expect(crumbLabel("/admin/offices")).toBe("Offices");
    expect(crumbLabel("/alerts")).toBe("Alerts");
    expect(crumbLabel("/calendar")).toBe("My calendar");
    expect(crumbLabel("/cases/x/alerts")).toBe("Alerts");
    expect(crumbLabel("/alerts/calendar")).toBe("Hearing calendar");
    expect(CRUMB_PATHS["/files"]).toBe("Files");
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
    expect(entry.label).toBe("Cause list");
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
    expect(CRUMB_PATHS["/reports/hearings-disposals"]).toBe("Hearings and disposals");
    expect(crumbLabel("/reports/pending-actions")).toBe("Pending actions");
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
    expect(CRUMBS.audit).toBe("Audit log");
    expect(crumbLabel("/audit")).toBe("Audit log");
    expect(crumbLabel("/audit/0192a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b")).toBe(AUDIT_ENTRY_CRUMB);
    expect(AUDIT_ENTRY_CRUMB).toBe("Entry");
  });
});

describe("System health navigation (api-health-checker, decision 2)", () => {
  it("the entry shows only with admin.service_health, in Settings after Data collection", () => {
    const entry = NAV.find((e) => e.key === "system")!;
    expect(entry).toMatchObject({ href: "/system", group: "settings", label: "System health", functions: ["admin.service_health"] });
    expect(navFor({ functions: ["admin.service_health"] }).map((e) => e.key)).toEqual(["dashboard", "system"]);
    for (const fn of ["admin.napix_refetch", "admin.masters_sync", "reports.state", "admin.data_load"] as const) {
      expect(navFor(only(fn)).map((e) => e.key)).not.toContain("system");
    }
    const keys = NAV.map((e) => e.key);
    expect(keys.indexOf("system")).toBe(keys.indexOf("data") + 1);
    expect(keys.indexOf("admin")).toBe(keys.indexOf("system") + 1);
    expect(crumbLabel("/system")).toBe("System health");
  });
});

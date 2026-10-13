import { describe, expect, it } from "vitest";

import type { Permission, Role } from "./api/types";
import { tracksDepartment } from "./can";
import {
  ADMIN_FUNCTIONS,
  ADMIN_TABS,
  adminTabsFor,
  alertsTabsFor,
  CASE_TABS,
  CRUMB_PATHS,
  crumbLabel,
  CRUMBS,
  filesTabsFor,
  MAPPING_FUNCTIONS,
  mappingTabsFor,
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
    expect(keys(mappingTabsFor(only("admin.keywords")))).toEqual(["keywords", "scoring"]);
    expect(keys(mappingTabsFor(only("admin.watchlist")))).toEqual(["watchlist"]);
    expect(keys(mappingTabsFor(only("admin.scoring")))).toEqual(["scoring"]);
    expect(mappingTabsFor(only("users.view"))).toEqual([]);
    expect(mappingTabsFor(null)).toEqual([]);
  });
});

describe("the case page tabs (portal-workflow)", () => {
  it("include Custody and stage after Overview and Alerts after Notes, without a count on Alerts", () => {
    const tabs = CASE_TABS.map((t) => t.key);
    expect(tabs.slice(0, 2)).toEqual(["", "custody"]);
    expect(tabs[tabs.indexOf("notes") + 1]).toBe("alerts");
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

describe("Files and Alerts & calendar navigation (portal-files-alerts)", () => {
  it("Alerts & calendar shows for case readers", () => {
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

  it("the Alerts frame has two tabs for case readers", () => {
    expect(keys(alertsTabsFor({ functions: ["cases.view_scope"] }))).toEqual(["list", "calendar"]);
    expect(alertsTabsFor({ functions: ["users.view"] })).toEqual([]);
  });

  it("CRUMB_PATHS names the screens by path, while the segments keep their meaning", () => {
    expect(crumbLabel("/files/offices")).toBe("My offices");
    expect(crumbLabel("/admin/offices")).toBe("Offices");
    expect(crumbLabel("/alerts")).toBe("Alerts & calendar");
    expect(crumbLabel("/cases/x/alerts")).toBe("Alerts");
    expect(crumbLabel("/alerts/calendar")).toBe("Hearing calendar");
    expect(CRUMB_PATHS["/files"]).toBe("Files");
  });
});

describe("the Cause list navigation (portal-causelist)", () => {
  it("shows for cases.view_scope and for cases.view_all, right after Search, and not without them", () => {
    for (const fn of ["cases.view_scope", "cases.view_all"] as const) {
      const keys = navFor({ functions: [fn], memberships: [] }).map((e) => e.key);
      expect(keys).toContain("causelist");
      expect(keys.indexOf("causelist")).toBe(keys.indexOf("search") + 1);
    }
    expect(navFor({ functions: ["users.view"] }).map((e) => e.key)).not.toContain("causelist");
    expect(navFor({ functions: [] }).map((e) => e.key)).not.toContain("causelist");
    const entry = navFor({ functions: ["cases.view_scope"] }).find((e) => e.key === "causelist")!;
    expect(entry.label).toBe("Cause list");
    expect(entry.href).toBe("/causelist");
  });
});

import { describe, expect, it } from "vitest";

import type { Permission } from "./api/types";
import { ADMIN_FUNCTIONS, ADMIN_TABS, adminTabsFor, MAPPING_FUNCTIONS, mappingTabsFor, PEOPLE_ADMIN_FUNCTIONS } from "./routes";

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

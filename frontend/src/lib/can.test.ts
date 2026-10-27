import { describe, expect, it } from "vitest";

import type { Me, Permission, Role } from "@/lib/api/types";
import { makeMe } from "@/test/render";

import { usersStateWide } from "./can";

function at(kind: "state" | "department", role: Role, functions: Permission[]): Me {
  return makeMe(functions, role, {
    memberships: [
      {
        id: "m-1",
        office: { code: kind === "state" ? "GOA" : "EDU", name: "x", kind },
        department_code: kind === "state" ? null : "EDU",
        designation: null,
        role,
        is_primary: true,
        is_active: true,
        functions,
      },
    ],
  });
}

describe("usersStateWide (design office-head-picker-followups, decision 4)", () => {
  it("the Super Administrator", () => {
    expect(usersStateWide(at("state", "super_admin", ["users.view"]))).toBe(true);
  });

  it("a holder of cases.view_all", () => {
    expect(usersStateWide(at("state", "state_oversight", ["users.view", "cases.view_all"]))).toBe(true);
  });

  it("not a State-office users.view holder without cases.view_all", () => {
    expect(usersStateWide(at("state", "state_oversight", ["users.view"]))).toBe(false);
  });

  it("not a department admin", () => {
    expect(usersStateWide(at("department", "dept_admin", ["users.view", "users.create", "offices.manage"]))).toBe(false);
    expect(usersStateWide(undefined)).toBe(false);
  });
});

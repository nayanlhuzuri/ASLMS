/**
 * Audit action names (design portal-names-and-labels, decisions 21-22): every code the backend registers
 * (`AUDIT_ACTIONS`, exported to `enumCodes.json`) has a Title Case name in `T.audit.actionNames`, every prefix has a
 * group label in `T.audit.groups`, and no name is left for a code outside the registry.
 */
import { describe, expect, it } from "vitest";

import { actionName } from "./audit";
import codes from "./enumCodes.json";
import { T } from "./messages";
import { isTitleCase } from "./titleCase";

const REGISTRY = codes.audit_actions;

describe("audit action names", () => {
  it("names every registered action code in Title Case", () => {
    expect(REGISTRY.length).toBeGreaterThan(100);
    expect(REGISTRY.filter((c) => !T.audit.actionNames[c])).toEqual([]);
    expect(REGISTRY.filter((c) => T.audit.actionNames[c] && !isTitleCase(T.audit.actionNames[c]!))).toEqual([]);
  });

  it("labels every prefix as a group", () => {
    const prefixes = [...new Set(REGISTRY.map((c) => c.slice(0, c.indexOf("."))))];
    expect(prefixes.filter((p) => !T.audit.groups[p])).toEqual([]);
  });

  it("keeps no name for a code outside the registry", () => {
    expect(Object.keys(T.audit.actionNames).filter((c) => !REGISTRY.includes(c))).toEqual([]);
    const prefixes = new Set(REGISTRY.map((c) => c.slice(0, c.indexOf("."))));
    expect(Object.keys(T.audit.groups).filter((g) => !prefixes.has(g))).toEqual([]);
  });

  it("gives every name once, so the Action filter never shows two equal names", () => {
    const names = Object.values(T.audit.actionNames);
    expect(names.filter((n, i) => names.indexOf(n) !== i)).toEqual([]);
  });

  it("shows the code itself for a code with no name", () => {
    expect(actionName("ownership.claim")).toBe("Case Claimed");
    expect(actionName("made.up_code")).toBe("made.up_code");
  });
});

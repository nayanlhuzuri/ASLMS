/**
 * Every enum used on screen has a label (design portal-names-and-labels, decision 16, K4). The enums are every string
 * enum of `openapi.json` (named schemas, and inline properties as `Schema.property`) and every domain enum of
 * `enumCodes.json` (the ones the API sends as plain strings). Each sits in exactly one list of `enumLabels.ts`; a
 * labelled enum has a label for every value and none for a value it lacks; no list names an enum that is gone.
 */
import { describe, expect, it } from "vitest";

import openapi from "../../openapi.json";
import codes from "./enumCodes.json";
import { LABELLED, NOT_SHOWN, SERVER_LABELLED } from "./enumLabels";
import { isTitleCase } from "./titleCase";

type Node = { enum?: unknown[]; anyOf?: Node[]; oneOf?: Node[]; allOf?: Node[]; items?: Node; properties?: Record<string, Node> };

function stringEnum(node: Node | undefined): string[] | null {
  if (!node) return null;
  if (Array.isArray(node.enum) && node.enum.every((v) => typeof v === "string")) return node.enum as string[];
  for (const key of ["anyOf", "oneOf", "allOf"] as const) {
    for (const x of node[key] ?? []) {
      const found = stringEnum(x);
      if (found) return found;
    }
  }
  return node.items ? stringEnum(node.items) : null;
}

function allEnums(): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const schemas = (openapi as { components: { schemas: Record<string, Node> } }).components.schemas;
  for (const [name, schema] of Object.entries(schemas)) {
    const own = stringEnum(schema.enum ? schema : undefined);
    if (own) {
      out.set(name, own);
      continue;
    }
    for (const [prop, node] of Object.entries(schema.properties ?? {})) {
      const values = stringEnum(node);
      if (values) out.set(`${name}.${prop}`, values);
    }
  }
  for (const [name, values] of Object.entries(codes.enums)) if (!out.has(name)) out.set(name, values);
  return out;
}

const ENUMS = allEnums();
const LISTS = { LABELLED: Object.keys(LABELLED), SERVER_LABELLED: Object.keys(SERVER_LABELLED), NOT_SHOWN: Object.keys(NOT_SHOWN) };

describe("enum labels", () => {
  it("finds the API's and the domain's enums", () => {
    expect(ENUMS.size).toBeGreaterThan(100);
    expect(ENUMS.get("CaseStatus")).toEqual(["pending", "disposed", "unknown"]);
    expect(ENUMS.get("NextHearingOut.basis")).toBeTruthy();
  });

  it("puts every enum in exactly one list", () => {
    const placed = (name: string) => Object.entries(LISTS).filter(([, names]) => names.includes(name)).map(([list]) => list);
    const unplaced = [...ENUMS.keys()].filter((name) => placed(name).length === 0);
    const twice = [...ENUMS.keys()].filter((name) => placed(name).length > 1);
    expect(unplaced, "add these to LABELLED, SERVER_LABELLED or NOT_SHOWN in lib/enumLabels.ts").toEqual([]);
    expect(twice).toEqual([]);
  });

  it("names no enum that no longer exists", () => {
    const stale = Object.values(LISTS)
      .flat()
      .filter((name) => !ENUMS.has(name));
    expect(stale).toEqual([]);
  });

  it("labels every value of a labelled enum, in Title Case unless the map holds sentences", () => {
    const missing: string[] = [];
    const notTitle: string[] = [];
    for (const [name, { map, sentence }] of Object.entries(LABELLED)) {
      for (const value of ENUMS.get(name) ?? []) {
        const label = map[value];
        if (!label) missing.push(`${name}.${value}`);
        else if (!sentence && !isTitleCase(label)) notTitle.push(`${name}.${value}: ${label}`);
      }
    }
    expect(missing).toEqual([]);
    expect(notTitle).toEqual([]);
  });

  it("keeps no stale label: a labelled map's keys are values of some enum that uses it", () => {
    const byMap = new Map<Readonly<Record<string, string>>, Set<string>>();
    for (const [name, { map, extra }] of Object.entries(LABELLED)) {
      const values = byMap.get(map) ?? new Set<string>();
      for (const v of [...(ENUMS.get(name) ?? []), ...(extra ?? [])]) values.add(v);
      byMap.set(map, values);
    }
    const stale: string[] = [];
    for (const [map, values] of byMap) {
      for (const key of Object.keys(map)) if (key && !values.has(key)) stale.push(key);
    }
    // a map may also carry the screen's own extra choices ("", "all", "any"); those are not enum values
    expect(stale.filter((k) => !["all", "any", "both", "none"].includes(k))).toEqual([]);
  });

  it("gives every exception a reason", () => {
    for (const reason of [...Object.values(NOT_SHOWN), ...Object.values(SERVER_LABELLED)]) expect(reason.length).toBeGreaterThan(5);
  });
});

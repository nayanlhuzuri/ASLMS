/**
 * The Title Case guard over every string of `T` (design portal-ui-polish-2, decision 4): label paths are Title Case,
 * unclassified short strings are Title Case or declared in `SENTENCE_EXCEPTIONS`, the `LABEL_FUNCTIONS` results are
 * Title Case, and no exception or function entry is stale. The rules live in `labelRules.ts`.
 */
import { describe, expect, it } from "vitest";

import { LABEL_FUNCTIONS, SENTENCE_EXCEPTIONS, classify, isLabelPath, looksLikeLabel } from "./labelRules";
import { T } from "./messages";
import { isTitleCase } from "./titleCase";

interface Leaf {
  path: string;
  value: unknown;
}

/** Every string or function leaf of `T` with its dotted path (array items by index). */
export function leaves(node: unknown, prefix = ""): Leaf[] {
  if (typeof node === "string" || typeof node === "function") return [{ path: prefix, value: node }];
  if (node && typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => leaves(v, prefix ? `${prefix}.${k}` : k));
  }
  return [];
}

const ALL = leaves(T);
const PATHS = new Set(ALL.map((l) => l.path));

describe("the Title Case guard over messages.ts", () => {
  it("walks the whole of T", () => {
    expect(ALL.length).toBeGreaterThan(1000);
    expect(PATHS.has("nav.inbox")).toBe(true);
  });

  it("writes every label path in Title Case", () => {
    const bad = ALL.filter((l) => typeof l.value === "string" && isLabelPath(l.path) && !isTitleCase(l.value as string)).map(
      (l) => `${l.path}: ${String(l.value)}`,
    );
    expect(bad).toEqual([]);
  });

  it("writes every unclassified short string in Title Case unless it declares itself a sentence", () => {
    const bad = ALL.filter(
      (l) =>
        typeof l.value === "string" &&
        classify(l.path) === "unclassified" &&
        !(l.path in SENTENCE_EXCEPTIONS) &&
        looksLikeLabel(l.value) &&
        !isTitleCase(l.value),
    ).map((l) => `${l.path}: ${String(l.value)}`);
    expect(bad).toEqual([]);
  });

  it("gives Title Case results for the label functions", () => {
    const bad: string[] = [];
    for (const [path, args] of Object.entries(LABEL_FUNCTIONS)) {
      const leaf = ALL.find((l) => l.path === path);
      if (!leaf || typeof leaf.value !== "function") continue;
      const out = (leaf.value as (...a: unknown[]) => unknown)(...args);
      if (typeof out !== "string" || !isTitleCase(out)) bad.push(`${path}: ${String(out)}`);
    }
    expect(bad).toEqual([]);
  });

  it("has no stale exception or function entry", () => {
    const stale = [
      ...Object.keys(SENTENCE_EXCEPTIONS).filter((p) => !PATHS.has(p) || ALL.find((l) => l.path === p)?.value === undefined),
      ...Object.keys(LABEL_FUNCTIONS).filter((p) => typeof ALL.find((l) => l.path === p)?.value !== "function"),
    ];
    expect(stale).toEqual([]);
    for (const reason of Object.values(SENTENCE_EXCEPTIONS)) expect(reason.trim().length).toBeGreaterThan(5);
  });

  it("lists exceptions only for unclassified strings", () => {
    const misplaced = Object.keys(SENTENCE_EXCEPTIONS).filter((p) => classify(p) !== "unclassified");
    expect(misplaced).toEqual([]);
  });
});

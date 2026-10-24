/**
 * The checker's own rules (design followups-oct, decision 22): on a redirect only the geometry kinds are dropped; no
 * browser is opened.
 */
import { expect, test } from "@playwright/test";

import { GEOMETRY_KINDS } from "./checks";
import { kept, type Finding } from "./results";

function finding(kind: string): Finding {
  return { route: "/files", width: 375, kind, element: "x", detail: "y" };
}

const OTHER = ["missing-fixture", "not-get", "console-error", "page-error"];
const ALL = [...GEOMETRY_KINDS.map(finding), ...OTHER.map(finding)];

test("kept drops only geometry kinds on a redirect", () => {
  expect(kept(ALL, true).map((f) => f.kind)).toEqual(OTHER);
});

test("kept keeps everything without a redirect", () => {
  expect(kept(ALL, false)).toEqual(ALL);
  expect(kept([], true)).toEqual([]);
});

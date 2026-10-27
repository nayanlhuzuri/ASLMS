/**
 * The checker's own rules (design followups-oct, decision 22): on a redirect only the geometry kinds are dropped (no
 * page needed); and the field-row checkbox step on two small pages of its own (design portal-ui-polish-2, decision 26).
 */
import { expect, test } from "@playwright/test";

import { GEOMETRY_KINDS, pageChecks } from "./checks";
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

/**
 * The checkbox step of the field-row check (design portal-ui-polish-2, decision 26): in a row of labelled fields a
 * checkbox sits on the 36 px control line, level with the boxes, not with the labels. One page breaks the rule and one
 * keeps it.
 */
function fieldRow(checkStyle: string): string {
  return `<!doctype html><html><body style="margin:0;font:14px sans-serif">
    <form style="display:flex;gap:12px;align-items:flex-start;padding:16px">
      <div><label for="a" style="display:block;height:20px;margin-bottom:4px">Name</label>
        <input id="a" style="height:36px;box-sizing:border-box;margin:0"></div>
      <div style="display:flex;align-items:center;gap:8px;${checkStyle}">
        <input type="checkbox" id="c" style="width:16px;height:16px;margin:0"><label for="c">Include Sub-offices</label></div>
      <button type="submit" style="height:36px;margin-top:24px">Search</button>
    </form></body></html>`;
}

test("a checkbox level with the labels is a field-row finding", async ({ page }) => {
  await page.setContent(fieldRow("min-height:24px"));
  const findings = await page.evaluate(pageChecks, { width: 1280 });
  const checkbox = findings.filter((f) => f.kind === "alignment" && f.detail.startsWith("field row: checkbox centre"));
  expect(checkbox).toHaveLength(1);
});

test("a checkbox on the control line passes", async ({ page }) => {
  // CheckField inline: a top margin of the label line plus its gap, 36 px tall, centred
  await page.setContent(fieldRow("margin-top:24px;min-height:36px"));
  const findings = await page.evaluate(pageChecks, { width: 1280 });
  expect(findings.filter((f) => f.detail.startsWith("field row: checkbox centre"))).toEqual([]);
});

/**
 * The gutter and doubled-heading rules (design data-collection-redesign, decision 12): each on a page that breaks it and
 * a page that keeps it.
 */
function shell(mainStyle: string, body: string): string {
  return `<!doctype html><html><body style="margin:0;font:14px sans-serif">
    <main id="main" style="${mainStyle}">${body}</main></body></html>`;
}

test("a 3 px page gutter and a value pushing past the content box are gutter findings", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 3px;width:600px",
      `<p>Data Collection</p><div style="width:900px">A long error that does not wrap</div>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "gutter");
  expect(findings.some((f) => f.detail.startsWith("left padding 3.0 px"))).toBe(true);
  expect(findings.some((f) => f.detail.startsWith("box "))).toBe(true);
});

test("a kept gutter, a sideways-scroll region and a visually hidden caption pass the gutter rule", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px;width:600px",
      `<p style="overflow-wrap:anywhere">A long value that wraps inside the page</p>
       <div data-scroll-x style="overflow-x:auto"><div style="width:900px">A wide report table</div></div>
       <span style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Hidden</span>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "gutter");
  expect(findings).toEqual([]);
});

test("a caption repeating its panel heading is a doubled heading", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      `<section><h2>Work Left</h2><table><caption>Work Left</caption><tbody><tr><td>1</td></tr></tbody></table></section>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "doubled-heading");
  expect(findings).toHaveLength(1);
});

test("a hidden caption or a different heading passes the doubled-heading rule", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      `<section><h2>Work Left</h2>
         <table><caption style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Work Left</caption>
           <tbody><tr><td>1</td></tr></tbody></table>
         <h3>By Kind of Work</h3></section>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "doubled-heading");
  expect(findings).toEqual([]);
});

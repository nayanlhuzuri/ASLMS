/**
 * The checker's own rules (design followups-oct, decision 22): on a redirect only the geometry kinds are dropped (no
 * page needed); and the field-row checkbox step on two small pages of its own (design portal-ui-polish-2, decision 26).
 */
import { expect, test, type Page } from "@playwright/test";

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

/**
 * The field-row pages are measured as at 1280 px (the width `pageChecks` is given), whatever the project's viewport: at
 * 375 px the row is wider than the page, so "Include Sub-offices" wrapped onto two lines and the checkbox's box grew.
 */
async function atLaptop(page: Page): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 800 });
}

test("a checkbox level with the labels is a field-row finding", async ({ page }) => {
  await atLaptop(page);
  await page.setContent(fieldRow("min-height:24px"));
  const findings = await page.evaluate(pageChecks, { width: 1280 });
  const checkbox = findings.filter((f) => f.kind === "alignment" && f.detail.startsWith("field row: checkbox centre"));
  expect(checkbox).toHaveLength(1);
});

test("a checkbox on the control line passes", async ({ page }) => {
  // CheckField inline: a top margin of the label line plus its gap, 36 px tall, centred
  await atLaptop(page);
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

/**
 * The clipped rule's text-field exemption (owner, 28 Oct 2026): a long value in a text input or a textarea scrolls
 * inside the field and passes; a box that cuts off its content still fails, and so does an input of another type.
 */
function clipPage(body: string): string {
  return `<!doctype html><html><body style="margin:0;font:14px sans-serif"><main id="main" style="padding:16px">${body}</main></body></html>`;
}

const LONG = "Joint Secretary to the Government of Assam, Department of School Education and Literacy";

test("a long value in a text input or a textarea is not clipped content", async ({ page }) => {
  await page.setContent(
    clipPage(
      `<input type="text" style="width:200px;height:36px;box-sizing:border-box" value="${LONG}">
       <input style="width:200px;height:36px;box-sizing:border-box" value="${LONG}">
       <textarea style="width:200px;white-space:nowrap;overflow:hidden">${LONG}</textarea>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "clipped");
  expect(findings).toEqual([]);
});

test("a box that cuts off its content is still clipped content", async ({ page }) => {
  await page.setContent(clipPage(`<div style="width:200px;overflow:hidden;white-space:nowrap">${LONG}</div>`));
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "clipped");
  expect(findings).toHaveLength(1);
  expect(findings[0]!.element.startsWith("div")).toBe(true);
});

test("a button whose label is cut off is still clipped content (the exemption is for text fields only)", async ({ page }) => {
  await page.setContent(clipPage(`<button style="width:120px;overflow:hidden;white-space:nowrap">${LONG}</button>`));
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "clipped");
  expect(findings).toHaveLength(1);
});

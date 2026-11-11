/**
 * The checker's own rules (design followups-oct, decision 22): on a redirect only the geometry kinds are dropped (no
 * page needed); and the field-row checkbox step on two small pages of its own (design portal-ui-polish-2, decision 26);
 * the box collector and boxdiff (design portal-navy-cream, decision 16).
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { compareRuns, differences, main, report, type Boxes } from "./boxdiff";
import { collectBoxes } from "./boxes";
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

/**
 * The menu-clipped rule (design case-inbox-simplify, decision 23): a menu list cut by a box that scrolls sideways fails;
 * the same list placed `position: fixed` passes; with no menu open nothing is measured.
 */
const MENU_ITEMS = `<li><a role="menuitem" href="#">Parties</a></li><li><a role="menuitem" href="#">Linked Cases</a></li>
  <li><a role="menuitem" href="#">Details</a></li>`;

test("a menu cut off by a sideways-scrolling bar is a menu-clipped finding", async ({ page }) => {
  await page.setContent(
    clipPage(
      `<nav data-scroll-x style="overflow-x:auto;position:relative;height:40px;white-space:nowrap">
         <span style="position:relative;display:inline-block">
           <button>More</button>
           <ul role="menu" style="position:absolute;top:100%;left:0;margin:0;padding:0;list-style:none;background:#fff">${MENU_ITEMS}</ul>
         </span>
       </nav>`,
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "menu-clipped");
  expect(findings.length).toBeGreaterThan(0);
});

test("a menu placed fixed over the page passes, and a page with no menu raises nothing", async ({ page }) => {
  await page.setContent(
    clipPage(
      `<nav data-scroll-x style="overflow-x:auto;height:40px"><button>More</button></nav>
       <ul role="menu" style="position:fixed;top:60px;left:16px;z-index:40;margin:0;padding:0;list-style:none;background:#fff">${MENU_ITEMS}</ul>`,
    ),
  );
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "menu-clipped")).toEqual([]);
  await page.setContent(clipPage("<p>No menu here</p>"));
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "menu-clipped")).toEqual([]);
});

/**
 * The four rules of design portal-ui-kit-fixes (decisions 24 and 33), each on a page that breaks it and one that keeps
 * it: caption inset (and the squeeze of a caption in a table drawn as cards), date wrap, broken word and card row.
 */
function table(captionStyle: string): string {
  return `<table style="border-collapse:separate;border-spacing:0;width:600px">
      <caption style="text-align:left;${captionStyle}">To Us</caption>
      <thead><tr><th style="padding:12px 16px;text-align:left">Case</th><th style="padding:12px 16px">From</th></tr></thead>
      <tbody><tr><td style="padding:12px 16px">WP(C)/1/2026</td><td style="padding:12px 16px">Health</td></tr></tbody>
    </table>`;
}

test("a caption flush with the table's edge is a caption-inset finding", async ({ page }) => {
  await page.setContent(shell("padding:16px 24px", table("padding:8px 0")));
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "caption-inset");
  expect(findings).toHaveLength(1);
});

test("a caption inset like the cells, or marked as a heading, passes", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      `${table("padding:12px 16px 8px")}
       <table style="width:300px"><caption data-caption="heading" style="text-align:left">October 2026</caption>
         <thead><tr><th style="padding:8px">Mon</th></tr></thead><tbody><tr><td style="padding:8px">1</td></tr></tbody></table>`,
    ),
  );
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "caption-inset")).toEqual([]);
});

test("a caption squeezed in a 60 px box of a table drawn as cards is a caption-inset finding", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      `<table style="display:block;width:300px"><caption style="display:table-caption;width:60px">Cause-list Entries</caption>
         <tbody style="display:block"><tr style="display:block"><td data-label="Case" style="display:block">WP(C)/1/2026</td></tr></tbody></table>`,
    ),
  );
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "caption-inset")).toHaveLength(1);
});

test("a date broken over lines in a 40 px cell is a date-wrap finding; with no-break spaces in a wide cell it passes", async ({ page }) => {
  await page.setContent(shell("padding:16px 24px", `<div style="width:40px">23 Oct 2026</div>`));
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "date-wrap")).toHaveLength(1);
  await page.setContent(shell("padding:16px 24px", `<div style="width:300px">Due 23\u00a0Oct\u00a02026</div>`));
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "date-wrap")).toEqual([]);
});

test("a word broken in the middle is a broken-word finding; inside data-free-text it passes", async ({ page }) => {
  await page.setContent(shell("padding:16px 24px", `<div style="width:30px;overflow-wrap:anywhere">October</div>`));
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "broken-word")).toHaveLength(1);
  await page.setContent(shell("padding:16px 24px", `<div data-free-text style="width:30px;overflow-wrap:anywhere">October</div>`));
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "broken-word")).toEqual([]);
});

function cards(rows: string): string {
  // each cell's label is drawn by ::before from data-label, as in the kit
  return `<style>td::before { content: attr(data-label); }</style>
    <table style="display:block;width:340px"><tbody style="display:block">${rows}</tbody></table>`;
}

const CELL = "display:grid;grid-template-columns:112px minmax(0,1fr);column-gap:12px;align-items:baseline";

test("an empty labelled cell on a card is a card-row finding", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      cards(`<tr style="display:block">
        <td data-label="Case" style="${CELL}"><div style="grid-column:2">WP(C)/1/2026</div></td>
        <td data-label="Status" style="${CELL}"><div style="grid-column:2"></div></td></tr>`),
    ),
  );
  const findings = (await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "card-row");
  expect(findings).toHaveLength(1);
  expect(findings[0]!.detail).toContain("Status");
});

test("values starting at different x on one card are a card-row finding; one column passes", async ({ page }) => {
  await page.setContent(
    shell(
      "padding:16px 24px",
      cards(`<tr style="display:block">
        <td data-label="Due" style="display:flex;justify-content:space-between"><div>23 Oct 2026</div></td>
        <td data-label="What the Order Says" style="display:flex;gap:12px"><div>Reply in two weeks</div></td></tr>`),
    ),
  );
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "card-row")).toHaveLength(1);
  await page.setContent(
    shell(
      "padding:16px 24px",
      cards(`<tr style="display:block">
        <td data-label="Due" style="${CELL}"><div style="grid-column:2">23 Oct 2026</div></td>
        <td data-label="What the Order Says" style="${CELL}"><div style="grid-column:2">Reply in two weeks</div></td>
        <td data-label="Actions" style="${CELL}"><div style="grid-column:2"><button>Confirm</button></div></td></tr>`),
    ),
  );
  expect((await page.evaluate(pageChecks, { width: 1280 })).filter((f) => f.kind === "card-row")).toEqual([]);
});

/**
 * The screen box comparison (design portal-navy-cream, decision 16): the collector records each element's path and box
 * and does not see a class change; boxdiff finds a 1 px shift, a missing element and a changed page height, and exits
 * non-zero, while two identical runs give no difference.
 */
function boxPage(extra: string, cls = "a"): string {
  return `<!doctype html><html><body style="margin:0;font:14px sans-serif">
    <main class="${cls}" style="padding:16px"><h1 style="margin:0;height:30px">Title</h1>
      <p style="margin:${extra};height:20px">One</p><p style="margin:0;height:20px">Two</p>
      <script>window.x = 1;</script></main></body></html>`;
}

test("the box collector records each element's path and box and ignores a class change", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(boxPage("0"));
  const first = await page.evaluate(collectBoxes);
  expect(Object.keys(first.boxes)).toEqual(["body>main:1", "body>main:1>h1:1", "body>main:1>p:1", "body>main:1>p:2"]);
  expect(first.boxes["body>main:1>h1:1"]).toEqual([16, 16, 1248, 30]);
  expect(first.boxes["body>main:1>p:2"]).toEqual([16, 66, 1248, 20]);
  expect(first.scrollWidth).toBe(1280);
  await page.setContent(boxPage("0", "b other-class"));
  const renamed = await page.evaluate(collectBoxes);
  expect(renamed).toEqual(first);
});

function boxRun(boxes: Record<string, [number, number, number, number]>, scrollHeight = 800): Boxes {
  return { name: "/", width: 1280, scrollWidth: 1280, scrollHeight, boxes };
}

const BASE = { "body>main:1": [0, 0, 1280, 100], "body>main:1>p:1": [16, 16, 200, 20] } as Record<string, [number, number, number, number]>;

test("boxdiff gives 0 differences for identical runs and within 0.5 px", () => {
  const same = compareRuns({ "dashboard-1280": boxRun(BASE) }, { "dashboard-1280": boxRun({ ...BASE }) });
  expect(differences(same)).toBe(0);
  expect(report(same)[0]).toBe("0 moved, 0 missing, 0 extra, 0 page-size changes");
  const half = compareRuns({ p: boxRun(BASE) }, { p: boxRun({ ...BASE, "body>main:1>p:1": [16.5, 16, 200, 20] }) });
  expect(differences(half)).toBe(0);
});

test("boxdiff reports a 1 px shift, a missing element, an extra one and a changed page height", () => {
  const diff = compareRuns(
    { p: boxRun(BASE), gone: boxRun(BASE) },
    { p: boxRun({ "body>main:1": [0, 0, 1280, 100], "body>main:1>div:1": [0, 0, 10, 10] }, 801), q: boxRun(BASE) },
  );
  expect(diff.moved).toBe(0);
  expect(diff.pages[0]!.missing).toEqual(["body>main:1>p:1"]);
  expect(diff.pages[0]!.extra).toEqual(["body>main:1>div:1"]);
  expect(diff.pages[0]!.size).toBe("1280x800 -> 1280x801");
  expect(diff.missingPages).toEqual(["gone"]);
  expect(diff.extraPages).toEqual(["q"]);
  const shifted = compareRuns({ p: boxRun(BASE) }, { p: boxRun({ ...BASE, "body>main:1>p:1": [16, 17, 200, 20] }) });
  expect(shifted.moved).toBe(1);
  expect(shifted.pages[0]!.moved[0]).toContain("body>main:1>p:1 [16, 16, 200, 20] -> [16, 17, 200, 20]");
});

test("boxdiff exits non-zero on a difference and 0 on none, reading the run folders", () => {
  const root = mkdtempSync(join(tmpdir(), "boxdiff-"));
  const write = (run: string, file: string, data: Boxes) => {
    mkdirSync(join(root, run, "20261111-1200", "boxes"), { recursive: true });
    writeFileSync(join(root, run, "20261111-1200", "boxes", `${file}.json`), JSON.stringify(data));
  };
  write("a1", "dashboard-1280", boxRun(BASE));
  write("a2", "dashboard-1280", boxRun(BASE));
  write("b", "dashboard-1280", boxRun(BASE, 900));
  const log = console.log;
  console.log = () => undefined;
  try {
    expect(main([join(root, "a1"), join(root, "a2")])).toBe(0);
    expect(main([join(root, "a1"), join(root, "b")])).toBe(1);
    expect(main([join(root, "a1")])).toBe(2);
  } finally {
    console.log = log;
    rmSync(root, { recursive: true, force: true });
  }
});

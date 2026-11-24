/**
 * Makes the run directory `<UICHECK_OUT or /out>/<YYYYMMDD-HHMM>` and passes it to the workers. In boxes mode (design
 * portal-navy-cream, decision 16) it also fixes the run's pinned instant, `UICHECK_CLOCK`, once for every worker.
 *
 * It also writes `layout-probe.js` into the run directory (design data-collection-gutter-live-check, decision 1): the
 * geometry rules of `pageChecks` as a console snippet for a signed-in browser, so the live check measures with the same
 * rule as the screen check and no second copy can drift.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { boxesEnabled, clockInstant } from "./boxes";
import { pageChecks } from "./checks";

/** The snippet's file name in the run directory. */
export const PROBE_FILE = "layout-probe.js";

/**
 * The console snippet: `pageChecks` serialised by `Function.prototype.toString`, as Playwright serialises it for
 * `page.evaluate`, wrapped to run once at the window's own width. It prints the findings with `console.table` and
 * returns their count. It only measures: no request, no storage, no change to the page.
 */
export function layoutProbe(): string {
  return `/*
 * ASLMS layout probe (design data-collection-gutter-live-check, decision 1). Written by the screen check (uicheck)
 * into its run folder; never part of the portal.
 *
 * What it is: the screen check's own geometry rules (pageChecks in frontend/e2e/checks.ts: gutter, page-overflow,
 * off-screen and every other geometry kind), run once on the page that is open.
 * What it does: it only measures. It makes no request, reads no storage and changes nothing on the page. It prints
 * the findings as a table and returns their count (0 when the page passes).
 *
 * Where to run it: signed in as the Super Administrator, paste it into the DevTools console (Chrome asks once for
 * "allow pasting") on each page and state below, at 375, 768 and 1280 px (DevTools responsive mode) and at your own
 * window width:
 *   /data/overview   with Waiting Work opened and Month by Month scrolled to its end
 *   /data/automatic  with the schedule and Search by Department Names in view
 *   /data/collect    with the Requests list showing and one request's items opened
 *   /data/problems   with every section drawn
 *   /system#calls
 * Send back the printed table, or "0", per page and width.
 */
(() => {
  const f = ${pageChecks.toString()};
  const r = f({ width: document.documentElement.clientWidth });
  console.table(r);
  return r.length;
})();
`;
}

export default function globalSetup(): void {
  const now = new Date(Date.now() + 5.5 * 3600_000); // IST, as the portal's dates
  const stamp = now.toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
  const dir = join(process.env.UICHECK_OUT ?? "/out", stamp);
  mkdirSync(join(dir, "results"), { recursive: true });
  writeFileSync(join(dir, PROBE_FILE), layoutProbe());
  process.env.UICHECK_RUN_DIR = dir;
  process.env.UICHECK_STARTED = String(Date.now());
  if (boxesEnabled()) {
    process.env.UICHECK_CLOCK = clockInstant();
    mkdirSync(join(dir, "boxes"), { recursive: true });
  }
}

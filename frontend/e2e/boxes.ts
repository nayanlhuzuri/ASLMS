/**
 * The screen box comparison (design portal-navy-cream, decision 16). With `UICHECK_BOXES=1` every route and interaction
 * state, at each width, also writes `boxes/<slug>-<width>.json`: every rendered element's stable path (tag and
 * `nth-of-type` from `body`, which a class change does not alter) and its box rounded to 0.5 px in page coordinates,
 * plus the document's scroll width and height. It is collected after `document.fonts.ready`, under the run's reduced
 * motion, with the page clock pinned to one IST instant (`UICHECK_CLOCK`, set once per run by the global setup) so
 * greetings, "Today" bands and relative dates render the same text in both runs. `boxdiff.ts` compares two runs.
 * Without `UICHECK_BOXES` nothing here runs and the check behaves exactly as before.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Page } from "@playwright/test";

import { runDir, slug } from "./results";

/** One page's boxes: `[x, y, width, height]` by element path. */
export interface BoxFile {
  name: string;
  width: number;
  scrollWidth: number;
  scrollHeight: number;
  boxes: Record<string, [number, number, number, number]>;
}

export function boxesEnabled(): boolean {
  return process.env.UICHECK_BOXES === "1";
}

/**
 * The run's pinned instant: `UICHECK_CLOCK` when set (an ISO instant), otherwise 12:00 IST of the day it is evaluated.
 * The global setup fixes it once per run, so every worker and the fixtures read the same instant.
 */
export function clockInstant(now: Date = new Date()): string {
  if (process.env.UICHECK_CLOCK) return new Date(process.env.UICHECK_CLOCK).toISOString();
  const ist = new Date(now.getTime() + 5.5 * 3_600_000).toISOString().slice(0, 10);
  return new Date(`${ist}T12:00:00+05:30`).toISOString();
}

/** Pins the page's clock in boxes mode only (before the first navigation); otherwise does nothing. */
export async function pinClock(page: Page): Promise<void> {
  if (!boxesEnabled()) return;
  await page.clock.setFixedTime(new Date(clockInstant()));
}

/**
 * Runs in the page (self-contained, for `page.evaluate`): the box of every element under `body`, keyed by its path of
 * tag names and `nth-of-type` indexes. Script, style and template elements carry no box and are left out.
 */
export function collectBoxes(): Omit<BoxFile, "name" | "width"> {
  const SKIP = new Set(["script", "style", "noscript", "template", "link", "meta"]);
  const half = (v: number) => Math.round(v * 2) / 2;
  const boxes: Record<string, [number, number, number, number]> = {};
  const sx = window.scrollX;
  const sy = window.scrollY;
  const walk = (el: Element, path: string) => {
    const counts = new Map<string, number>();
    for (const child of Array.from(el.children)) {
      const tag = child.tagName.toLowerCase();
      if (SKIP.has(tag)) continue;
      const n = (counts.get(tag) ?? 0) + 1;
      counts.set(tag, n);
      const childPath = `${path}>${tag}:${n}`;
      const r = child.getBoundingClientRect();
      boxes[childPath] = [half(r.left + sx), half(r.top + sy), half(r.width), half(r.height)];
      walk(child, childPath);
    }
  };
  walk(document.body, "body");
  return { scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight, boxes };
}

/** Collects and writes the page's boxes in boxes mode only, after the fonts are ready. */
export async function writeBoxes(page: Page, name: string, width: number): Promise<void> {
  if (!boxesEnabled()) return;
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const data = await page.evaluate(collectBoxes);
  const file: BoxFile = { name, width, ...data };
  mkdirSync(join(runDir(), "boxes"), { recursive: true });
  writeFileSync(join(runDir(), "boxes", `${slug(name)}-${width}.json`), JSON.stringify(file));
}

/**
 * Compares the boxes of two uicheck runs (design portal-navy-cream, decision 16): `npm run boxdiff -- <before> <after>`
 * in the uicheck image, each argument a run folder (`/out/a1`, holding `<stamp>/boxes/*.json`, or the stamp folder
 * itself). It reports every element whose box moved or resized by more than 0.5 px, every element present in one run
 * only, every page present in one run only and every page whose size differs, and exits non-zero on any of them.
 *
 * Self-contained (node built-ins only) so that Node runs it directly with its type stripping; the uicheck self-test
 * imports the same functions.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** Mirrors `BoxFile` in boxes.ts (kept apart so this file needs no local import). */
export interface Boxes {
  name: string;
  width: number;
  scrollWidth: number;
  scrollHeight: number;
  boxes: Record<string, [number, number, number, number]>;
}

export interface PageDiff {
  page: string;
  moved: string[];
  missing: string[];
  extra: string[];
  size: string | null;
}

export interface RunDiff {
  pages: PageDiff[];
  missingPages: string[];
  extraPages: string[];
  moved: number;
  missing: number;
  extra: number;
  pageSize: number;
}

const TOLERANCE = 0.5;

/** The differences of one page between two runs. */
export function comparePage(page: string, before: Boxes, after: Boxes): PageDiff {
  const moved: string[] = [];
  const missing: string[] = [];
  const extra: string[] = [];
  for (const [path, a] of Object.entries(before.boxes)) {
    const b = after.boxes[path];
    if (!b) {
      missing.push(path);
      continue;
    }
    const delta = a.map((v, i) => Math.abs(v - b[i]!));
    if (delta.some((d) => d > TOLERANCE)) moved.push(`${path} [${a.join(", ")}] -> [${b.join(", ")}]`);
  }
  for (const path of Object.keys(after.boxes)) if (!(path in before.boxes)) extra.push(path);
  const size =
    before.scrollWidth !== after.scrollWidth || before.scrollHeight !== after.scrollHeight
      ? `${before.scrollWidth}x${before.scrollHeight} -> ${after.scrollWidth}x${after.scrollHeight}`
      : null;
  return { page, moved, missing, extra, size };
}

/** The differences of two runs, page by page (pages keyed by their file name, `<slug>-<width>`). */
export function compareRuns(before: Record<string, Boxes>, after: Record<string, Boxes>): RunDiff {
  const pages: PageDiff[] = [];
  const missingPages = Object.keys(before).filter((p) => !(p in after)).sort();
  const extraPages = Object.keys(after).filter((p) => !(p in before)).sort();
  for (const page of Object.keys(before).sort()) {
    const b = after[page];
    if (!b) continue;
    const diff = comparePage(page, before[page]!, b);
    if (diff.moved.length || diff.missing.length || diff.extra.length || diff.size) pages.push(diff);
  }
  const sum = (key: "moved" | "missing" | "extra") => pages.reduce((n, p) => n + p[key].length, 0);
  return {
    pages,
    missingPages,
    extraPages,
    moved: sum("moved"),
    missing: sum("missing") + missingPages.length,
    extra: sum("extra") + extraPages.length,
    pageSize: pages.filter((p) => p.size).length,
  };
}

export function differences(diff: RunDiff): number {
  return diff.moved + diff.missing + diff.extra + diff.pageSize;
}

/** The `boxes` folder of a run: `<dir>/boxes`, or the newest `<dir>/<stamp>/boxes`. */
export function boxesDir(dir: string): string {
  if (existsSync(join(dir, "boxes"))) return join(dir, "boxes");
  const stamps = readdirSync(dir)
    .filter((n) => existsSync(join(dir, n, "boxes")) && statSync(join(dir, n, "boxes")).isDirectory())
    .sort();
  const last = stamps[stamps.length - 1];
  if (!last) throw new Error(`no boxes folder under ${dir} (run uicheck with UICHECK_BOXES=1)`);
  return join(dir, last, "boxes");
}

export function readRun(dir: string): Record<string, Boxes> {
  const folder = boxesDir(dir);
  const out: Record<string, Boxes> = {};
  for (const name of readdirSync(folder).filter((n) => n.endsWith(".json"))) {
    out[name.replace(/\.json$/, "")] = JSON.parse(readFileSync(join(folder, name), "utf-8")) as Boxes;
  }
  return out;
}

const SHOWN = 40;

/** The report as lines: the totals first, then each page's differences (at most 40 lines of each kind per page). */
export function report(diff: RunDiff): string[] {
  const lines = [
    `${diff.moved} moved, ${diff.missing} missing, ${diff.extra} extra, ${diff.pageSize} page-size changes`,
  ];
  for (const p of diff.missingPages) lines.push(`page only in the first run: ${p}`);
  for (const p of diff.extraPages) lines.push(`page only in the second run: ${p}`);
  for (const p of diff.pages) {
    lines.push(`${p.page}:`);
    if (p.size) lines.push(`  page size ${p.size}`);
    for (const [label, items] of [
      ["moved", p.moved],
      ["missing", p.missing],
      ["extra", p.extra],
    ] as const) {
      for (const item of items.slice(0, SHOWN)) lines.push(`  ${label} ${item}`);
      if (items.length > SHOWN) lines.push(`  ... and ${items.length - SHOWN} more ${label}`);
    }
  }
  return lines;
}

/** The command: prints the report and returns the exit code (0 only with no difference at all). */
export function main(args: string[]): number {
  const [a, b] = args;
  if (!a || !b) {
    console.error("usage: npm run boxdiff -- <before run folder> <after run folder>");
    return 2;
  }
  const diff = compareRuns(readRun(a), readRun(b));
  for (const line of report(diff)) console.log(line);
  return differences(diff) === 0 ? 0 : 1;
}

if (process.env.UICHECK_BOXDIFF_CLI === "1") process.exitCode = main(process.argv.slice(2));

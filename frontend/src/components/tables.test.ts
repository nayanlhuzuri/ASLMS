/**
 * No sideways scrolling on phones (design portal-ui-polish, decision 15): every list is the kit's `DataTable`, which
 * shows cards on phones. A raw `<table>` stays only in the kit itself, the wide report tables (`ReportView`, kept
 * scrollable), the cause list's `EntryTable` (already cards on phones) and the month grids (`MonthGrid`,
 * `DepartmentHearings`); the plain `Table` left the kit.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

const SOURCES = [...files(join(SRC, "components")), ...files(join(SRC, "app"))].map((f) => ({
  file: relative(SRC, f).split(sep).join("/"),
  text: readFileSync(f, "utf-8"),
}));

const RAW_TABLE_ALLOWED = new Set([
  "components/ui/data.tsx",
  "components/reports/ReportView.tsx",
  "components/causelist/EntryTable.tsx",
  "components/calendar/MonthGrid.tsx",
  "components/calendar/DepartmentHearings.tsx",
]);

describe("tables (design portal-ui-polish, decision 15)", () => {
  it("no raw <table> outside the kit, ReportView, EntryTable, MonthGrid and DepartmentHearings", () => {
    const raw = SOURCES.filter(({ file, text }) => !RAW_TABLE_ALLOWED.has(file) && /<table[\s>]/.test(text)).map((s) => s.file);
    expect(raw).toEqual([]);
  });

  it("nothing imports Table from the kit", () => {
    const importers = SOURCES.filter(({ text }) =>
      [...text.matchAll(/import\s*\{([^}]*)\}\s*from\s*"@\/components\/ui(?:\/data)?"/g)].some((m) =>
        m[1]!.split(",").some((n) => n.replace(/^\s*type\s+/, "").trim() === "Table"),
      ),
    ).map((s) => s.file);
    expect(importers).toEqual([]);
    const kit = readFileSync(join(SRC, "components", "ui", "data.tsx"), "utf-8");
    expect(kit).not.toMatch(/export function Table\b/);
  });
});

/**
 * The source companion of uicheck's `doubled-heading` rule (design data-collection-redesign, decisions 10 and 12): a
 * `DataTable` caption is hidden by default, so a table that shows its caption (`showCaption`) must not repeat a
 * heading, card title or summary of the same file in the same words.
 */
describe("doubled headings (design data-collection-redesign, decision 12)", () => {
  function shownCaptions(text: string): string[] {
    const out: string[] = [];
    for (const m of text.matchAll(/<DataTable\b([\s\S]*?)\/>/g)) {
      const props = m[1]!;
      if (!/\bshowCaption\b(?!=\{false\})/.test(props)) continue;
      const caption = /caption=\{([^}]+)\}/.exec(props);
      if (caption) out.push(caption[1]!.trim());
    }
    return out;
  }

  function headings(text: string): Set<string> {
    const out = new Set<string>();
    for (const m of text.matchAll(/<h[1-4][^>]*>\s*\{([^}]+)\}\s*<\/h[1-4]>/g)) out.add(m[1]!.trim());
    for (const m of text.matchAll(/\b(?:title|summary)=\{([^}]+)\}/g)) out.add(m[1]!.trim());
    return out;
  }

  it("no shown caption repeats a heading of its file", () => {
    const doubled = SOURCES.flatMap(({ file, text }) => {
      const heads = headings(text);
      return shownCaptions(text)
        .filter((c) => heads.has(c))
        .map((c) => `${file}: ${c}`);
    });
    expect(doubled).toEqual([]);
  });

  it("the rule sees a doubled heading and passes a distinct one", () => {
    const bad = '<h2>{T.a}</h2>\n<DataTable caption={T.a} showCaption rows={r} rowKey={k} columns={c} />';
    const good = '<h2>{T.a}</h2>\n<DataTable caption={T.a} rows={r} rowKey={k} columns={c} />';
    expect(shownCaptions(bad).filter((c) => headings(bad).has(c))).toEqual(["T.a"]);
    expect(shownCaptions(good)).toEqual([]);
  });
});

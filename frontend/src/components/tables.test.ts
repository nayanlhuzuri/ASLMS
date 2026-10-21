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

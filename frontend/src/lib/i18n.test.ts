import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatDateTimeSeconds, formatNumber, formatTime, formatWeekday } from "./format";
import { CATALOGUES, DEFAULT_LOCALE, htmlAttributes, LOCALES, messagesFor, type LocaleInfo } from "./i18n";
import { T } from "./messages";

const SRC = join(process.cwd(), "src");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) files(path, out);
    else out.push(path);
  }
  return out;
}

/** The source files a user-facing string could live in: no tests, no test helpers, no generated API types. */
const SOURCES = files(SRC).filter(
  (f) =>
    /\.(ts|tsx)$/.test(f) &&
    !/\.test\.(ts|tsx)$/.test(f) &&
    !f.includes(`${sep}test${sep}`) &&
    !f.endsWith(`${sep}schema.d.ts`) &&
    !f.endsWith(`${sep}messages.ts`),
);

describe("the page's language (design portal-ui-redesign, decision 27)", () => {
  it('is lang="en" dir="ltr" from the locale', () => {
    expect(htmlAttributes()).toEqual({ lang: "en", dir: "ltr" });
    expect(htmlAttributes(DEFAULT_LOCALE)).toEqual({ lang: "en", dir: "ltr" });
    expect(htmlAttributes("xx")).toEqual({ lang: "en", dir: "ltr" });
    const layout = readFileSync(join(SRC, "app", "layout.tsx"), "utf-8");
    expect(layout).toContain("htmlAttributes(DEFAULT_LOCALE)");
    expect(layout).toMatch(/<html lang=\{lang\} dir=\{dir\}>/);
  });

  it("an unknown catalogue falls back to English", () => {
    expect(messagesFor("en")).toBe(T);
    expect(messagesFor("xx")).toBe(T);
  });

  it("inherited keys fall back to English (design portal-ui-polish, decision 4)", () => {
    for (const key of ["toString", "constructor", "__proto__", "hasOwnProperty"]) {
      expect(messagesFor(key)).toBe(T);
      expect(htmlAttributes(key)).toEqual({ lang: "en", dir: "ltr" });
    }
  });
});

/** Every key path of a catalogue with its kind: a string, a function and its arity, or an object. */
function shape(value: unknown, path = "", out: Record<string, string> = {}): Record<string, string> {
  if (typeof value === "function") out[path] = `fn/${value.length}`;
  else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) shape(v, path ? `${path}.${k}` : k, out);
  } else out[path] = typeof value;
  return out;
}

describe("message catalogues", () => {
  it("every catalogue in LOCALES has the English keys and function arities", () => {
    const english = shape(T);
    expect(Object.keys(english).length).toBeGreaterThan(500);
    for (const code of Object.keys(LOCALES)) {
      expect(shape(CATALOGUES[code as keyof typeof CATALOGUES])).toEqual(english);
    }
    expect(Object.keys(CATALOGUES).sort()).toEqual(Object.keys(LOCALES).sort());
  });

  it("the navigation, tab, breadcrumb and group labels live in messages.ts", () => {
    expect(T.nav.groups).toEqual({ work: "Work", oversight: "Oversight", settings: "Settings" });
    expect(T.nav.inbox).toBe("Case inbox");
    expect(T.crumbs.mapping).toBe("Department mapping");
  });
});

describe("dates and numbers by locale", () => {
  it("English keeps today's fixed texts (the existing cases)", () => {
    expect(formatDate("2026-09-24T19:00:00Z", "en")).toBe("25 Sep 2026");
    expect(formatDate("2026-01-01", "en")).toBe("1 Jan 2026");
    expect(formatDateTime("2026-09-24T18:30:00Z", "en")).toBe("25 Sep 2026, 00:00");
    expect(formatDateTimeSeconds("2026-10-14T09:04:07Z", "en")).toBe("14 Oct 2026, 14:34:07");
    expect(formatTime("2026-10-11T09:04:30Z", "en")).toBe("14:34");
    expect(formatNumber(128400, "en")).toBe("1,28,400");
    expect(formatNumber(12345678)).toBe("1,23,45,678");
    expect(formatWeekday("2026-10-20")).toBe("Tuesday");
  });

  it("any other locale goes through Intl, in IST", () => {
    const other: LocaleInfo = { code: "xx", htmlLang: "xx", intl: "en-US", dir: "ltr" };
    const instant = "2026-09-24T19:00:00Z";
    expect(formatDate(instant, other)).toBe(
      new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" }).format(
        new Date(instant),
      ),
    );
    expect(formatDate(instant, other)).toContain("25");
    expect(formatNumber(128400, other)).toBe("128,400");
    expect(formatWeekday("2026-10-20", other)).toBe("Tuesday");
  });
});

describe("no user-facing text outside messages.ts", () => {
  it("no navigation label is left in routes.ts", () => {
    const routes = readFileSync(join(SRC, "lib", "routes.ts"), "utf-8");
    expect(routes).not.toMatch(/label:\s*"/);
    expect(routes).not.toMatch(/:\s*"[A-Z][a-z]+( [a-z]+)*",?\s*$/m);
  });

  // allowed: code, symbols and case data (no word of two letters or more)
  const words = /[A-Za-z]{2,}/;

  it("no JSX text literal and no label: \"…\" outside messages.ts", () => {
    const found: string[] = [];
    for (const file of SOURCES) {
      const text = readFileSync(file, "utf-8");
      const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      const where = (node: ts.Node) => `${relative(SRC, file)}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
      const visit = (node: ts.Node) => {
        if (ts.isJsxText(node) && words.test(node.getText())) found.push(`${where(node)} JSX "${node.getText().trim()}"`);
        if (
          ts.isPropertyAssignment(node) &&
          node.name.getText() === "label" &&
          (ts.isStringLiteral(node.initializer) || ts.isNoSubstitutionTemplateLiteral(node.initializer)) &&
          words.test(node.initializer.text)
        ) {
          found.push(`${where(node)} label "${node.initializer.text}"`);
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
    expect(found).toEqual([]);
  });
});

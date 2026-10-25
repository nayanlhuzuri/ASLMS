/**
 * One primary action per screen, across the whole portal (design portal-ui-redesign, decision 16; round 5 tests):
 * every page under `src/app` is rendered, inside its own section layouts, with a fake `/me` holding every function,
 * and may show at most one element with the primary style (a primary `Button`, or a link drawn as one). Pages whose
 * data the fake API does not answer render their error or empty state, which must keep the rule as well; the round
 * tests check the screens with their data.
 */
import { act, render } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { AuditRow, Permission, Report, ReportCatalogue } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

const APP = join(process.cwd(), "src", "app");
const SRC = join(process.cwd(), "src");

/** Every function the API knows, read from the generated schema, so the fake login sees every entry and button. */
function allFunctions(): Permission[] {
  const schema = readFileSync(join(SRC, "lib", "api", "schema.d.ts"), "utf-8");
  const line = schema.split("\n").find((l) => l.trim().startsWith("Permission: "))!;
  return [...line.matchAll(/"([a-z_]+\.[a-z_]+)"/g)].map((m) => m[1] as Permission);
}

function pages(dir = APP): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "api") out.push(...pages(path));
    } else if (name === "page.tsx") out.push(path);
  }
  return out.sort();
}

/** The URL of a page file (route groups left out, dynamic segments filled in). */
function routeOf(file: string): string {
  const parts = relative(APP, file).split(sep).slice(0, -1);
  return (
    "/" +
    parts
      .filter((p) => !(p.startsWith("(") && p.endsWith(")")))
      .map((p) => (p.startsWith("[") ? SAMPLE[p.slice(1, -1)] ?? "x" : p))
      .join("/")
  );
}

/** The layouts between the root (and the portal shell) and the page, outermost first. */
function layoutsOf(file: string): string[] {
  const parts = relative(APP, file).split(sep).slice(0, -1);
  const out: string[] = [];
  for (let i = 1; i <= parts.length; i += 1) {
    const dir = join(APP, ...parts.slice(0, i));
    const layout = join(dir, "layout.tsx");
    if (parts.slice(0, i).join("/") === "(portal)") continue; // the shell: header, sidebar and counts, no primary
    try {
      if (statSync(layout).isFile()) out.push(layout);
    } catch {
      // no layout at this level
    }
  }
  return out;
}

const SAMPLE: Record<string, string> = { ref: "ASLMS-GOA-CASE-2026-000001", id: "u-9", code: "EDU", role: "dept_officer" };
const PARAMS = { params: Promise.resolve(SAMPLE), searchParams: Promise.resolve({}) };

type Component = (props: Record<string, unknown>) => ReactNode | Promise<ReactNode>;

async function element(file: string, children?: ReactNode): Promise<ReactNode> {
  const mod = (await import(/* @vite-ignore */ file)) as { default: Component };
  return mod.default({ ...PARAMS, children });
}

const ROW: AuditRow = {
  id: "r-1",
  at: "2026-10-14T05:00:00Z",
  action: "custody.sent",
  actor: { user_id: "u-2", name: "Anita Sharma", designation: "Under Secretary", office_code: "EDU" },
  case: null,
  entity_type: "custody",
  entity_id: null,
  ip: null,
  user_agent: null,
  before: null,
  after: {},
} as unknown as AuditRow;

const CATALOGUE: ReportCatalogue = {
  reports: ["pending-cases", "hearings-disposals", "pending-actions", "data-health"].map((key) => ({
    key,
    title: key,
    params: [],
    scopes: ["state", "department"],
    departments: key === "data-health" ? [] : ["EDU"],
  })),
  departments: [{ code: "EDU", name: "Education", is_active: true }],
} as unknown as ReportCatalogue;

function report(key: string): Report {
  return {
    key,
    title: "A report",
    scope: "state",
    department_code: null,
    params: {},
    generated_at: "2026-10-14T05:00:00Z",
    generated_by: { name: "Anita Sharma", designation: null, office_code: "GOA" },
    as_of_note: "As it stands today.",
    sections: [],
  } as unknown as Report;
}

function fakeApi() {
  const me = makeMe(allFunctions(), "super_admin");
  me.memberships = (me.memberships ?? []).map((m) => ({ ...m, functions: allFunctions() }));
  return browserApi({
    "GET /me": me,
    "GET /reference/labels": labels(),
    "GET /reports": CATALOGUE,
    "GET /reports/pending-cases": report("pending-cases"),
    "GET /reports/hearings-disposals": report("hearings-disposals"),
    "GET /reports/pending-actions": report("pending-actions"),
    "GET /reports/data-health": report("data-health"),
    "GET /audit": { items: [ROW], next_cursor: null },
    "GET /audit/actions": { actions: [] },
    "GET /audit/u-9": ROW,
    "GET /admin/users": () => json(200, [], { "x-total-count": "0" }),
    "GET /admin/offices/tree": [],
    "GET /admin/designations": [],
    "GET /admin/tickets": { items: [], total: 0, counts: { open: 0 } },
    // design case-workspace-admin: the user-type pages and the Cases list
    "GET /admin/permissions": [
      { code: "users.view", module: "users", label: "See users", description: "See people.", is_active: true, group: "people", group_label: "People and access", sort_in_group: 1 },
    ],
    "GET /admin/access/defaults": { dept_officer: { "users.view": true } },
    "GET /admin/access/overview": [{ code: "dept_officer", users: 3, functions_on: 1, functions_total: 1, changed_from_default: 0 }],
    "GET /admin/access/types/dept_officer": { "users.view": true },
    "GET /custody/held": { items: [], total: 0 },
    "GET /custody/sent": { items: [], total: 0 },
    "GET /custody/summary": { departments: [] },
  });
}

async function settle() {
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
}

const PAGES = pages();

/** Pages whose one primary is known, so the check is seen to render real content. */
const EXPECTED: Record<string, string[]> = {
  "/login": ["Sign In"],
  "/forgot": ["Send Code"],
  "/reports/pending-cases": ["Show Report"],
  "/audit": ["Search"],
  "/admin/users": ["Add User"],
  "/admin/access/dept_officer": ["Save Changes"],
  "/admin/offices": ["New Office"],
  "/admin/tickets": ["Propose a Head Change"],
};

beforeEach(() => {
  try {
    window.sessionStorage.clear();
  } catch {
    // no storage
  }
});

describe("every page has at most one primary action (decision 16)", () => {
  it("finds the portal's pages", () => {
    expect(PAGES.length).toBeGreaterThanOrEqual(70);
    expect(PAGES.map(routeOf)).toEqual(expect.arrayContaining(["/reports/pending-cases", "/audit", "/data/load", "/admin/users", "/login"]));
  });

  it.each(PAGES.map((p) => [routeOf(p), p]))("%s", async (route, file) => {
    resetNav(route);
    fakeApi();
    let tree = await element(file);
    for (const layout of layoutsOf(file).reverse()) tree = await element(layout, tree);
    const { container } = renderWithClient(tree as ReactElement);
    await settle();
    const primaries = primaryActions(container);
    expect(primaries.length, `${route}: ${primaries.join(", ")}`).toBeLessThanOrEqual(1);
    if (EXPECTED[route]) expect(primaries).toEqual(EXPECTED[route]);
  });

  it("the old Cases list segments are their own (redirect) pages, never read as a case reference (case-workspace-admin, decision 3; case-inbox-merge, decision 12)", () => {
    const routes = PAGES.map(routeOf);
    for (const seg of ["with-me", "sent", "pending"]) {
      expect(routes).toContain(`/cases/${seg}`);
      const file = PAGES.find((p) => routeOf(p) === `/cases/${seg}`)!;
      // a static segment outside the case page's frame
      expect(file).toContain("(list)");
      expect(layoutsOf(file).some((l) => l.includes("[ref]"))).toBe(false);
    }
    expect(routes).toEqual(expect.arrayContaining(["/inbox/sent", "/inbox/pending"]));
  });

  it("the not-found page renders too", async () => {
    const { default: NotFound } = await import("./not-found");
    const { container } = render(<NotFound />);
    expect(primaryActions(container)).toEqual(["Go to the Dashboard"]);
  });
});

const USE_CLIENT = /^(?:\s|\/\/[^\n]*\n|\/\*[\s\S]*?\*\/)*["']use client["']/;

function isClientText(text: string): boolean {
  return USE_CLIENT.test(text);
}

/** The modules a file re-exports from (`export * from`, `export { … } from`), type-only re-exports left out. */
function reexportsOf(text: string): string[] {
  const out: string[] = [];
  const reexport = /^\s*export\s+(type\s+)?(?:\*(?:\s+as\s+\w+)?|\{[^}]*\})\s+from\s+["']([^"']+)["']/gm;
  for (const m of text.matchAll(reexport)) {
    if (!m[1]) out.push(m[2]!);
  }
  return out;
}

/**
 * Whether a source file is a client module: it says `"use client"`, or it re-exports a client module, as the kit
 * barrel `components/ui/index.tsx` does (review of 21 Oct 2026: the barrel has no `"use client"` line of its own, and
 * `buttonClass` reached server files through it). `seen` guards against re-export cycles.
 */
function isClientFile(path: string, seen: Set<string> = new Set()): boolean {
  if (seen.has(path)) return false;
  seen.add(path);
  const text = readFileSync(path, "utf-8");
  if (isClientText(text)) return true;
  return reexportsOf(text).some((spec) => {
    const target = resolveImport(path, spec);
    return target !== null && isClientFile(target, seen);
  });
}

/** The source file an import names (`@/…` or relative), or null for a package, a stylesheet or anything unresolved. */
function resolveImport(from: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = join(from, "..", spec);
  else return null;
  if (/\.(css|json|svg|png)$/.test(spec)) return null;
  for (const candidate of [base, `${base}.tsx`, `${base}.ts`, join(base, "index.tsx"), join(base, "index.ts")]) {
    try {
      if (statSync(candidate).isFile() && /\.(ts|tsx)$/.test(candidate)) return candidate;
    } catch {
      // try the next shape
    }
  }
  return null;
}

interface ImportLine {
  spec: string;
  /** The value names imported (type-only names left out); `*` for a namespace import. */
  names: string[];
}

/** The import statements of a file, with the value names each brings in. */
function importsOf(text: string): ImportLine[] {
  const out: ImportLine[] = [];
  for (const m of text.matchAll(/^\s*import\s+(type\s+)?([^"';]*?)\s+from\s+["']([^"']+)["']/gm)) {
    if (m[1]) continue; // `import type { … }`
    const clause = m[2]!.trim();
    const names: string[] = [];
    const braces = clause.match(/\{([^}]*)\}/);
    const outside = clause.replace(/\{[^}]*\}/, "").split(",").map((x) => x.trim()).filter(Boolean);
    for (const part of outside) names.push(part.startsWith("*") ? "*" : part);
    if (braces) {
      for (const raw of braces[1]!.split(",")) {
        const item = raw.trim();
        if (!item || item.startsWith("type ")) continue;
        names.push(item.split(/\s+as\s+/)[0]!.trim());
      }
    }
    out.push({ spec: m[3]!, names });
  }
  return out;
}

/**
 * The rule of the round 5 smoke (the `buttonClass()` crash): a server file may take from a `"use client"` module
 * only components (capitalised names) and types, never a function or value it would call on the server.
 * `isClient` says whether an import (by its specifier) is a client module.
 */
function serverImportProblems(file: string, text: string, isClient: (spec: string) => boolean): string[] {
  const bad: string[] = [];
  for (const line of importsOf(text)) {
    if (!isClient(line.spec)) continue;
    for (const name of line.names) if (!/^[A-Z]/.test(name)) bad.push(`${file}: ${name} from ${line.spec}`);
  }
  return bad;
}

/**
 * Every server file reached from the server files of `src/app` (design portal-ui-polish, decision 16): the walk follows
 * `@/` and relative imports through `src/components` and `src/lib`, and stops at `"use client"` files, the client
 * boundary. Returns the files reached and the problems found.
 */
function serverWalk(): { reached: string[]; problems: string[] } {
  const roots: string[] = [];
  const collect = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) collect(path);
      else if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) {
        if (!isClientText(readFileSync(path, "utf-8"))) roots.push(path);
      }
    }
  };
  collect(APP);
  const seen = new Set<string>();
  const problems: string[] = [];
  const queue = [...roots];
  while (queue.length > 0) {
    const file = queue.shift()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const text = readFileSync(file, "utf-8");
    const clientOf = new Map<string, boolean>();
    for (const line of importsOf(text)) {
      const target = resolveImport(file, line.spec);
      if (!target) continue;
      const client = isClientFile(target);
      clientOf.set(line.spec, client);
      if (!client && !target.startsWith(join(SRC, "server"))) queue.push(target);
    }
    for (const spec of reexportsOf(text)) {
      const target = resolveImport(file, spec);
      if (target && !target.startsWith(join(SRC, "server"))) queue.push(target);
    }
    problems.push(...serverImportProblems(relative(SRC, file), text, (spec) => clientOf.get(spec) === true));
  }
  return { reached: [...seen].map((f) => relative(SRC, f).split(sep).join("/")).sort(), problems };
}

describe("server files and client modules (portal smoke of 21 Oct 2026; design portal-ui-polish, decision 16)", () => {
  it("a server file imports only components and types from a client module, never a function it would call", () => {
    expect(serverWalk().problems).toEqual([]);
  });

  it("the guard follows server components rendered by server layouts", () => {
    const { reached } = serverWalk();
    expect(reached).toContain("components/auth/AuthFrame.tsx");
    expect(reached).toContain("app/(public)/layout.tsx");
  });

  it("the kit barrel, which only re-exports client modules, counts as a client module", () => {
    expect(isClientText(readFileSync(join(SRC, "components", "ui", "index.tsx"), "utf-8"))).toBe(false);
    expect(isClientFile(join(SRC, "components", "ui", "index.tsx"))).toBe(true);
    expect(isClientFile(resolveImport(join(APP, "not-found.tsx"), "@/components/ui")!)).toBe(true);
    expect(isClientFile(join(SRC, "lib", "messages.ts"))).toBe(false);
  });

  it("buttonClass from the kit barrel in a server file is caught with the real resolution", () => {
    const from = join(APP, "not-found.tsx");
    const fixture = 'import { buttonClass } from "@/components/ui";';
    const client = (spec: string) => {
      const target = resolveImport(from, spec);
      return target !== null && isClientFile(target);
    };
    expect(serverImportProblems("app/not-found.tsx", fixture, client)).toEqual([
      "app/not-found.tsx: buttonClass from @/components/ui",
    ]);
  });

  it('a server component importing a lowercase name from a "use client" module fails', () => {
    const fixture = [
      'import { Button, buttonClass, type Column } from "@/components/ui";',
      'import type { Me } from "@/lib/api/types";',
      'import { T } from "@/lib/messages";',
      'import Link, * as kit from "@/components/ui/controls";',
    ].join("\n");
    const client = (spec: string) => spec.startsWith("@/components/ui");
    expect(serverImportProblems("app/x/page.tsx", fixture, client)).toEqual([
      "app/x/page.tsx: buttonClass from @/components/ui",
      "app/x/page.tsx: * from @/components/ui/controls",
    ]);
  });
});

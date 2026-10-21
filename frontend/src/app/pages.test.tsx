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

const SAMPLE: Record<string, string> = { ref: "ASLMS-GOA-CASE-2026-000001", id: "u-9", code: "EDU" };
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
  "/login": ["Sign in"],
  "/forgot": ["Send code"],
  "/reports/pending-cases": ["Show report"],
  "/audit": ["Search"],
  "/admin/users": ["New user"],
  "/admin/offices": ["New office"],
  "/admin/tickets": ["Propose a head change"],
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

  it("the not-found page renders too", async () => {
    const { default: NotFound } = await import("./not-found");
    const { container } = render(<NotFound />);
    expect(primaryActions(container)).toEqual(["Go to the dashboard"]);
  });
});

/** Server files of `src/app` (no "use client"): what they import from the client UI kit. */
function serverKitImports(): { file: string; names: string[] }[] {
  const out: { file: string; names: string[] }[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) {
        const text = readFileSync(path, "utf-8");
        if (/^\s*["']use client["']/.test(text)) continue;
        for (const m of text.matchAll(/import\s*\{([^}]*)\}\s*from\s*"@\/components\/ui"/g)) {
          out.push({ file: relative(APP, path), names: m[1]!.split(",").map((n) => n.replace(/^\s*type\s+/, "").trim()).filter(Boolean) });
        }
      }
    }
  };
  walk(APP);
  return out;
}

describe("server pages and the client UI kit (portal smoke of 21 Oct 2026)", () => {
  it("a server file imports only components from the kit, never a function it would call on the server", () => {
    const bad = serverKitImports().flatMap(({ file, names }) => names.filter((n) => !/^[A-Z]/.test(n)).map((n) => `${file}: ${n}`));
    expect(bad).toEqual([]);
  });
});

/**
 * Component-test helpers: a fresh query client per test and a scripted relay. `browserApi({...})` answers
 * `fetch("/api/backend/…")` and `fetch("/api/session/…")` by "METHOD /path" (the query string ignored unless the
 * key has one); unknown calls answer 404 and are recorded.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import type { Me, Permission, ReferenceLabels, Role } from "@/lib/api/types";

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

type Answer = unknown | ((call: BrowserCall) => Response | unknown);

export interface BrowserCall {
  method: string;
  url: string;
  path: string;
  body: unknown;
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export function browserApi(routes: Record<string, Answer>) {
  const calls: BrowserCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.replace(/^\/api\/(backend|session)/, (_m, kind: string) => (kind === "session" ? "session:" : ""));
    let body: unknown = undefined;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    else if (init?.body instanceof FormData) body = init.body;
    const call = { method, url, path, body };
    calls.push(call);
    const bare = path.split("?")[0];
    const answer = routes[`${method} ${path}`] ?? routes[`${method} ${bare}`];
    if (answer === undefined) return json(404, { detail: "Not Found" });
    const value = await (typeof answer === "function" ? (answer as (c: BrowserCall) => unknown)(call) : answer);
    if (value instanceof Response) return value;
    return json(200, value);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const ALL_TYPES = [
  "super_admin",
  "state_oversight",
  "dept_head",
  "dept_admin",
  "dept_officer",
  "directorate_user",
  "referral_reviewer",
  "standing_counsel",
  "central_operator",
  "auditor",
] as const;

export function labels(assignable: readonly string[] = []): ReferenceLabels {
  return {
    user_types: ALL_TYPES.map((code) => ({
      code,
      label: code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
      description: null,
      assignable: assignable.includes(code),
    })),
    office_kinds: [
      { code: "state", label: "State" },
      { code: "department", label: "Department" },
      { code: "directorate", label: "Directorate" },
    ],
    ticket_kinds: [{ code: "head_change", label: "Head change" }],
    alert_kinds: [
      { code: "hearing_due", label: "Hearing due" },
      { code: "workflow", label: "File movement" },
    ],
  };
}

export function makeMe(functions: Permission[], role: Role = "dept_officer", extra: Partial<Me> = {}): Me {
  return {
    user: {
      id: "u-1",
      email: "anita@example.org",
      full_name: "Anita Sharma",
      role,
      office: { id: "o-1", code: "EDU", name: "Education", kind: "department", path: "GOA/EDU", is_active: true },
      designation: "Under Secretary",
      mobile: null,
      is_active: true,
      must_confirm_profile: false,
      must_change_password: false,
      last_login_at: null,
      created_at: "2026-10-01T00:00:00Z",
      memberships: [],
    },
    memberships: [
      {
        id: "m-1",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: "Under Secretary",
        role,
        is_primary: true,
        is_active: true,
      },
    ],
    functions,
    ...extra,
  };
}

/**
 * The elements drawn in the primary style (design portal-ui-redesign, decision 16: at most one per screen): a
 * primary `Button`, the global `.button-link`, and a link given `buttonClass("primary")`.
 */
export const PRIMARY_SELECTOR = "[data-variant='primary'], .button-link, a[class*='_primary_']";

export function primaryActions(root: ParentNode): string[] {
  return [...root.querySelectorAll(PRIMARY_SELECTOR)].map((e) => e.textContent ?? "");
}

/**
 * A converted list is a kit `DataTable` (design portal-ui-polish, decision 15): the table carries the `dataTable` class,
 * one cell per row is the primary cell on top of the phone card, and every other cell carries its `data-label` (or is
 * left out of the card with `hideOnPhone`, allowed only for a link the card reaches anyway). Returns the table.
 */
export function expectDataTable(table: HTMLElement): HTMLElement {
  if (table.tagName !== "TABLE") throw new Error(`expected a <table>, got <${table.tagName.toLowerCase()}>`);
  if (!/dataTable/.test(table.className)) throw new Error(`the table "${table.querySelector("caption")?.textContent ?? ""}" is not a DataTable`);
  const rows = [...table.querySelectorAll("tbody tr")];
  if (rows.length === 0) throw new Error("the DataTable has no rows");
  for (const row of rows) {
    const cells = [...row.children] as HTMLElement[];
    const primary = cells.filter((c) => /primaryCell/.test(c.className));
    if (primary.length !== 1) throw new Error(`a row has ${primary.length} primary cells`);
    for (const cell of cells) {
      if (/primaryCell|hideOnPhone/.test(cell.className)) continue;
      if (!cell.getAttribute("data-label")) throw new Error(`a cell has no data-label: "${cell.textContent ?? ""}"`);
    }
  }
  return table;
}

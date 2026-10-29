/**
 * Data Collection redesign, round 2 (design data-collection-redesign, decisions 2-4 and 42-46): Problems and Fixes
 * (sections with counts and empty states, the Court Connection line, Retry and Retry All by function, the duplicate
 * kinds, the data gaps with Collect These and Try Again by function, no primary), System Health's Court Calls section
 * only with both functions, and the old Health, Queue and Calls and Duplicates tabs gone with their redirects.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import { SystemHealth } from "@/components/system/SystemHealth";
import type { CallList, Duplicates as DuplicatesList, NapixHealth, Permission } from "@/lib/api/types";
import type { DataGaps, DataOverview } from "@/lib/dataCollection";
import { formatNumber } from "@/lib/format";
import { DATA_TABS, OLD_DATA_REDIRECTS } from "@/lib/routes";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";
import { routes as systemRoutes } from "@/test/systemFixtures";

import { DataFrame } from "./DataFrame";
import { ProblemsAndFixes } from "./ProblemsAndFixes";

const READER: Permission[] = ["reports.state"];
const OPERATOR: Permission[] = ["admin.napix_refetch", "admin.masters_sync", "reports.state"];
const MANAGER: Permission[] = ["admin.data_load"];
const SUPER: Permission[] = ["admin.data_load", "admin.napix_refetch", "admin.masters_sync", "reports.state", "admin.service_health"];

beforeEach(() => {
  resetNav("/data/problems");
});

const OVERVIEW = {
  as_of: "2026-10-26T10:00:00+05:30",
  napix_enabled: false,
  collection: "running",
  waiting_work: [
    { kind: "masters", total: 0, by_lane: { request: 0, daily: 0, discovery: 0, load: 0 }, running: 0, failed: 1 },
    { kind: "dossier", total: 33, by_lane: { request: 0, daily: 3, discovery: 0, load: 30 }, running: 0, failed: 11 },
    { kind: "order_pdf", total: 10, by_lane: { request: 0, daily: 10, discovery: 0, load: 0 }, running: 1, failed: 0 },
  ],
  problems: { failed: 12, duplicates_review: 3, cases_without_details: 109, orders_not_available: 8, orders_failed: 1 },
} as unknown as DataOverview;

const NO_PROBLEMS = {
  ...OVERVIEW,
  waiting_work: [],
  problems: { failed: 0, duplicates_review: 0, cases_without_details: 0, orders_not_available: 0, orders_failed: 0 },
} as unknown as DataOverview;

// the court-health block as the API answers it on a server whose court calls are on
const NAPIX = {
  enabled: true,
  est_code: "GAHC01",
  window: {
    status: "current",
    recent_resets: [
      { observed_at: "2026-10-26T09:34:30+05:30", previous_at: "2026-10-26T09:34:00+05:30", previous_remaining: 769, remaining: 999, precise: true },
      { observed_at: "2026-10-26T08:30:07+05:30", previous_at: "2026-10-26T07:30:07+05:30", previous_remaining: 148, remaining: 999, precise: false },
    ],
  },
  today: { calls: 120, failed: 3, by_family: {}, token_unverified: 0 },
  last_call_at: "2026-10-26T09:59:00+05:30",
  last_ok_at: "2026-10-26T09:31:00+05:30",
  last_failure: { api: "hc-cnr-api/CNR", called_at: "2026-10-26T09:59:00+05:30", error_family: "NapixUnavailable", http_status: 502, napix_status: null },
  last_check: null,
  by_user: null,
} as unknown as NapixHealth;

const row = (id: string, kind: string, ref: string, attempts: number, error: string) => ({
  id,
  kind,
  ref,
  priority: 60,
  status: "failed",
  attempts,
  not_before: null,
  started_at: null,
  finished_at: "2026-10-26T09:00:00+05:30",
  last_error: error,
  result: null,
  updated_at: "2026-10-26T09:00:00+05:30",
  lane: "daily",
  list_date: null,
});

const FAILED_ROWS = {
  total: 2,
  items: [
    row("q-1", "order_pdf", "GAHC010000012025|3|2025-03-01", 5, "NapixUnavailable: 502 Bad Gateway"),
    row("q-2", "masters", "all", 3, "NapixAuthError"),
  ],
};

const DOCS = {
  order: { pending: 3220, extracted: 57392, failed: 0, none: { scanned_pdf: 4, image: 0, doc: 0, other: 0 } },
  upload: { pending: 0, extracted: 14, failed: 11, none: { scanned_pdf: 12, image: 15, doc: 13, other: 0 } },
  attachment: { pending: 0, extracted: 0, failed: 0, none: { scanned_pdf: 0, image: 16, doc: 0, other: 0 } },
};

const brief = (n: number, cnr: string | null = `GAHC01000${n}2025`) => ({
  id: `c-${n}`,
  ref_no: `ASLMS/GHC/CASE/2026/00000${n}`,
  cnr,
  case_no_text: `WP(C)/${n}/2025`,
});

const CASES_GAP = {
  kind: "cases",
  total: 3,
  counts: { being_fetched: 1, not_found: 0, failed: 1, not_queued: 1 },
  items: [
    { case: brief(1), first_seen_at: "2026-10-20T10:00:00+05:30", state: "being_fetched", attempts: 0, problem: null },
    { case: brief(2), first_seen_at: "2026-10-19T10:00:00+05:30", state: "failed", attempts: 5, problem: "NapixUnavailable: 502" },
    { case: brief(3, null), first_seen_at: "2026-10-18T10:00:00+05:30", state: "not_queued", attempts: null, problem: null },
  ],
  documents_text: DOCS,
} as unknown as DataGaps;

const ORDERS_GAP = {
  kind: "orders",
  total: 2,
  counts: { not_available: 1, failed: 1 },
  items: [
    { case: brief(4), order_id: "o-1", order_no: "7", order_date: "2025-04-01", state: "failed", attempts: 2, problem: "HTTP 500 from the court" },
    { case: brief(5), order_id: "o-2", order_no: "2", order_date: "2025-03-01", state: "not_available", attempts: 1, problem: null },
  ],
  documents_text: DOCS,
} as unknown as DataGaps;

const emptyGap = (kind: string) => ({ kind, total: 0, counts: {}, items: [], documents_text: DOCS }) as unknown as DataGaps;

const DUPLICATES: DuplicatesList = {
  total: 1,
  items: [
    {
      kind: "review",
      case: { id: "p", ref_no: "ASLMS/GHC/CASE/2026/000009", cnr: null, case_no_text: "WPC/3600/2026" },
      other: { id: "c", ref_no: "ASLMS/GHC/CASE/2026/000002", cnr: "GAHC010129772026", case_no_text: "WP(C)/3600/2026" },
      at: "2026-10-11T03:00:00+05:30",
      reasons: "portal records on the provisional case: case_ownership",
    },
  ],
};

function problemRoutes(functions: Permission[], extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(functions, "central_operator"),
    "GET /admin/data-load/overview": OVERVIEW,
    "GET /admin/data-load/pulse": { last_call_at: "2026-10-26T09:59:00+05:30" },
    "GET /admin/napix/health": NAPIX,
    "GET /admin/napix/queue": FAILED_ROWS,
    "GET /admin/data-load/duplicates": DUPLICATES,
    "GET /admin/data-load/gaps": (c: { url: string }) => (c.url.includes("kind=orders") ? ORDERS_GAP : CASES_GAP),
    "GET /admin/data-health": {
      failures: [
        { kind: "text_extraction", open: 4, oldest_first_seen: "2026-10-20T10:00:00+05:30" },
        { kind: "some_new_kind", open: 1, oldest_first_seen: "2026-10-21T10:00:00+05:30" },
      ],
    },
    ...extra,
  });
}

describe("Problems and Fixes (decisions 42-46)", () => {
  it("shows the four sections in order, each heading with its count, and no primary", async () => {
    problemRoutes(OPERATOR);
    const { container } = renderWithClient(<ProblemsAndFixes />);
    expect(await screen.findByRole("heading", { name: "Failed Fetches (12)" })).toBeInTheDocument();
    const headings = [...container.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toEqual(["Court Connection", "Failed Fetches (12)", "Possible Duplicates (3)", "Data Gaps (118)"]);
    for (const id of ["failed", "duplicates", "gaps"]) expect(container.querySelector(`section#${id}`)).not.toBeNull();
    expect(await screen.findByRole("heading", { name: "Cases Without Details (3)" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Orders Not Available or Failed (2)" })).toBeInTheDocument();
    // documents not read: 4 + 11 + 12 + 15 + 13 + 16
    expect(await screen.findByRole("heading", { name: `Documents Without Searchable Text (${formatNumber(71)})` })).toBeInTheDocument();
    expect(primaryActions(container)).toEqual([]);
  });

  it("each section has an empty state", async () => {
    problemRoutes(OPERATOR, {
      "GET /admin/data-load/overview": NO_PROBLEMS,
      "GET /admin/data-load/duplicates": { total: 0, items: [] },
      "GET /admin/data-load/gaps": (c: { url: string }) => emptyGap(c.url.includes("kind=orders") ? "orders" : "cases"),
    });
    renderWithClient(<ProblemsAndFixes />);
    expect(await screen.findByText("No fetch has failed.")).toBeInTheDocument();
    expect(await screen.findByText("No case waits to be confirmed.")).toBeInTheDocument();
    expect(screen.getByText(/No data gap/)).toBeInTheDocument();
    expect(await screen.findByText("Every case held has its details from the court.")).toBeInTheDocument();
    expect(await screen.findByText("No order PDF is missing at the court or has failed.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Failed Fetches (0)" })).toBeInTheDocument();
  });

  it("the Court Connection line says the last failure in words, and the check is for the court operators", async () => {
    const api = problemRoutes(OPERATOR, { "POST /admin/napix/health/check": { ok: true, error_family: null } });
    const { unmount } = renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Court Connection" });
    expect(await within(section).findByText(/The last call failed at .*: the court did not answer \(busy or down\)\./)).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: "Check the Court Connection" }));
    expect(await within(section).findByText("The court answered the check.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/admin/napix/health/check")).toBe(true);
    unmount();
    // a reader without an operator's function sees the line and no button
    problemRoutes(READER, { "GET /admin/napix/health": { ...NAPIX, last_failure: null } });
    const second = renderWithClient(<ProblemsAndFixes />);
    const read = await screen.findByRole("region", { name: "Court Connection" });
    expect(await within(read).findByText(/The court answered at /)).toBeInTheDocument();
    expect(within(read).queryByRole("button")).toBeNull();
    second.unmount();
    // admin.data_load alone does not read the court-health block: the line comes from the pulse
    const only = problemRoutes(MANAGER);
    renderWithClient(<ProblemsAndFixes />);
    const manager = await screen.findByRole("region", { name: "Court Connection" });
    expect(await within(manager).findByText(/The last court call was at /)).toBeInTheDocument();
    expect(only.calls.some((c) => c.path === "/admin/napix/health")).toBe(false);
    expect(only.calls.some((c) => c.path.startsWith("/admin/napix/queue"))).toBe(false);
  });

  it("Failed Fetches: the summary by kind with Retry All and the failed items with Retry, each by its function", async () => {
    const api = problemRoutes(["admin.napix_refetch"], {
      "POST /admin/napix/queue/retry-failed": { kind: "dossier", retried: 11 },
      "POST /admin/napix/queue/q-1/retry": { kind: "order_pdf", ref: "x", status: "pending" },
    });
    renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Failed Fetches (12)" });
    // the reference lists need admin.masters_sync: no Retry All on that row, none on its item
    expect(within(section).queryByRole("button", { name: "Retry All Court Reference Lists" })).toBeNull();
    await userEvent.click(within(section).getByRole("button", { name: "Retry All Case Details" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === "/admin/napix/queue/retry-failed")?.body).toEqual({ kind: "dossier" }),
    );
    expect(await within(section).findByText("11 case details will be fetched again.")).toBeInTheDocument();
    const items = await within(section).findByRole("table", { name: "Failed Fetches" });
    expectDataTable(items);
    expect(within(items).getByText(/^Order 3 of .* · GAHC010000012025$/)).toBeInTheDocument();
    expect(within(items).getByText("All Court Reference Lists")).toBeInTheDocument();
    expect(within(items).getByText("NapixUnavailable: 502 Bad Gateway")).toBeInTheDocument();
    expect(within(items).getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    await userEvent.click(within(items).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/admin/napix/queue/q-1/retry")).toBe(true));
    expect(api.calls.find((c) => c.path.startsWith("/admin/napix/queue?"))?.url).toContain("status=failed");
  });

  it("the last connection check and the other recorded problems by kind, for readers of the court's health", async () => {
    const api = problemRoutes(READER, {
      "GET /admin/napix/health": {
        ...NAPIX,
        last_check: { called_at: "2026-10-26T09:40:00+05:30", ok: false, error_family: "NapixAuthError", duration_ms: 90, token_verified: false },
      },
    });
    const { unmount } = renderWithClient(<ProblemsAndFixes />);
    const connection = await screen.findByRole("region", { name: "Court Connection" });
    expect(await within(connection).findByText(/Last connection check .*: the access key or credentials were refused\./)).toBeInTheDocument();
    const failed = await screen.findByRole("region", { name: "Failed Fetches (12)" });
    const recorded = await within(failed).findByRole("table", { name: "Other Recorded Problems" });
    expect(within(recorded).getByText("Document Text Not Read")).toBeInTheDocument();
    expect(within(recorded).getByText("Some New Kind")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/admin/data-health")).toBe(true);
    unmount();
    const only = problemRoutes(MANAGER);
    renderWithClient(<ProblemsAndFixes />);
    await screen.findByRole("region", { name: "Failed Fetches (12)" });
    expect(screen.queryByRole("table", { name: "Other Recorded Problems" })).toBeNull();
    expect(only.calls.some((c) => c.path === "/admin/data-health")).toBe(false);
  });

  it("a reader sees every failed item and no button", async () => {
    problemRoutes(READER);
    renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Failed Fetches (12)" });
    await within(section).findByRole("table", { name: "Failed Fetches" });
    expect(within(section).queryByRole("button")).toBeNull();
    expect(screen.getByText(/You can see every problem/)).toBeInTheDocument();
  });

  it("Possible Duplicates: three kinds with a line each, Scan Now with admin.data_load only", async () => {
    problemRoutes(READER);
    const { unmount } = renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Possible Duplicates (3)" });
    expect(await within(section).findByText("portal records on the provisional case: case_ownership")).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Scan Now" })).toBeNull();
    unmount();
    const api = problemRoutes(MANAGER, {
      "POST /admin/data-load/duplicates/scan": { merged: 3, needs_review: 1, court_linked: 2 },
    });
    renderWithClient(<ProblemsAndFixes />);
    const manager = await screen.findByRole("region", { name: "Possible Duplicates (3)" });
    const kinds = within(manager).getByRole("radiogroup", { name: "Kind of Duplicate" });
    expect(within(kinds).getByRole("radio", { name: "To Confirm" })).toHaveAttribute("aria-checked", "true");
    expect(within(manager).getByText(/A person confirms it before anything is merged/)).toBeInTheDocument();
    expect(within(manager).getByText("Also runs every night at 03:00.")).toBeInTheDocument();
    await userEvent.click(within(manager).getByRole("button", { name: "Scan Now" }));
    expect(await within(manager).findByText("3 merged, 1 listed to confirm, 2 court duplicates linked.")).toBeInTheDocument();
    await userEvent.click(within(kinds).getByRole("radio", { name: "Court Duplicates" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("kind=court"))).toBe(true));
    expect(within(manager).getByText(/never merged/)).toBeInTheDocument();
  });

  it("Data Gaps: the cases with their state and Collect These for the ones not being fetched (admin.data_load)", async () => {
    const api = problemRoutes(MANAGER, {
      "POST /admin/data-load/fetch-details": {
        items: [
          { ref: "a", case: null, state: "queued", queue: null, merged_into_ref_no: null },
          { ref: "b", case: null, state: "queued", queue: null, merged_into_ref_no: null },
        ],
      },
    });
    renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Data Gaps (118)" });
    const table = await within(section).findByRole("table", { name: "Cases Without Details" });
    expectDataTable(table);
    expect(within(table).getByText("Being Fetched")).toBeInTheDocument();
    expect(within(table).getByText("NapixUnavailable: 502")).toBeInTheDocument();
    expect(within(table).getByText("Not Yet Queued")).toBeInTheDocument();
    expect(within(section).getByText("Failed · 1")).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: "Collect These" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === "/admin/data-load/fetch-details")?.body).toEqual({
        cases: ["ASLMS/GHC/CASE/2026/000002", "ASLMS/GHC/CASE/2026/000003"],
        force: false,
      }),
    );
    expect(await within(section).findByText("2 cases queued for their details.")).toBeInTheDocument();
    // Try Again needs admin.napix_refetch
    const orders = await within(section).findByRole("table", { name: "Orders Not Available or Failed" });
    expect(within(orders).queryByRole("button", { name: "Try Again" })).toBeNull();
  });

  it("Data Gaps: the orders with Try Again for admin.napix_refetch, and no Collect These without admin.data_load", async () => {
    const api = problemRoutes(["admin.napix_refetch"], {
      "POST /admin/napix/refetch/order": { kind: "order_pdf", ref: "x", status: "pending" },
    });
    renderWithClient(<ProblemsAndFixes />);
    const section = await screen.findByRole("region", { name: "Data Gaps (118)" });
    const orders = await within(section).findByRole("table", { name: "Orders Not Available or Failed" });
    expectDataTable(orders);
    expect(within(orders).getByText("Not Available at the Court")).toBeInTheDocument();
    expect(within(orders).getByText("HTTP 500 from the court")).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Collect These" })).toBeNull();
    await userEvent.click(within(orders).getAllByRole("button", { name: "Try Again" })[0]!);
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === "/admin/napix/refetch/order")?.body).toEqual({
        case: "ASLMS/GHC/CASE/2026/000004",
        order_id: "o-1",
      }),
    );
    expect(await within(section).findByText("The order PDF will be fetched again.")).toBeInTheDocument();
    const docs = within(section).getByRole("table", { name: "Documents Without Searchable Text" });
    expect(within(docs).getByRole("columnheader", { name: "Scanned PDFs, Not Read" })).toBeInTheDocument();
  });

  it("no heading is doubled: the section headings carry the names, the table captions stay hidden", async () => {
    problemRoutes(OPERATOR);
    const { container } = renderWithClient(<ProblemsAndFixes />);
    await screen.findByRole("table", { name: "Orders Not Available or Failed" });
    const captions = [...container.querySelectorAll("caption")];
    expect(captions.length).toBeGreaterThan(0);
    for (const caption of captions) expect(caption.className).toMatch(/srCaption/);
  });
});

describe("System Health's Court Calls section (decision 3)", () => {
  const CALLS = {
    items: [
      {
        id: "k-1",
        called_at: "2026-10-26T09:59:00+05:30",
        api: "hc-cnr-api/CNR",
        http_status: 502,
        napix_status: null,
        ok: false,
        error_family: "NapixUnavailable",
        error: null,
        duration_ms: 300,
        token_verified: true,
        rate_limit_remaining: 640,
        job_run_id: null,
        lane: "request",
        user_id: "u-1",
        user_name: "Rina Das",
      },
      {
        id: "k-2",
        called_at: "2026-10-26T09:58:00+05:30",
        api: "hc-party-name-api/partyname",
        http_status: 200,
        napix_status: null,
        ok: true,
        error_family: null,
        error: null,
        duration_ms: 300,
        token_verified: true,
        rate_limit_remaining: 641,
        job_run_id: null,
        lane: null,
        user_id: null,
        user_name: null,
      },
    ],
    next_cursor: "next",
  } as unknown as CallList;

  it("shows the resets, the e-mail and the call log in plain words, with More", async () => {
    systemRoutes(undefined, {
      "GET /me": makeMe(SUPER, "super_admin"),
      "GET /admin/napix/health": NAPIX,
      "GET /admin/data-health": { mail: { email_queued: 4, email_failed: 1 } },
      "GET /admin/napix/calls": CALLS,
    });
    renderWithClient(<SystemHealth params={{}} />);
    const section = await screen.findByRole("region", { name: "Court Calls" });
    const resets = await within(section).findByRole("table", { name: "Recent Resets" });
    expect(within(resets).getByText("Seen Exactly")).toBeInTheDocument();
    expect(within(resets).getByText("Estimated")).toBeInTheDocument();
    expect(within(resets).getByRole("columnheader", { name: "Calls Left Before" })).toBeInTheDocument();
    expect(await within(section).findByText("Waiting")).toBeInTheDocument();
    expect(within(section).getByText("4")).toBeInTheDocument();
    const log = await within(section).findByRole("table", { name: "Court Call Log" });
    expectDataTable(log);
    expect(within(log).getByTitle("hc-cnr-api/CNR")).toHaveTextContent("Case Details by CNR");
    expect(within(log).getByText("Search by Party Name")).toBeInTheDocument();
    expect(within(log).getByText("Failed: the court did not answer (busy or down)")).toBeInTheDocument();
    expect(within(log).getByText("Asked by People")).toBeInTheDocument();
    expect(within(log).getByText("Searches and Checks")).toBeInTheDocument();
    expect(within(log).getByRole("columnheader", { name: "Person" })).toBeInTheDocument();
    expect(within(log).getByText("Rina Das")).toBeInTheDocument();
    expect(within(section).getByRole("region", { name: "Court Call Log" })).toHaveAttribute("data-scroll-y");
    expect(within(section).getByRole("button", { name: "More" })).toBeInTheDocument();
  });

  it("is not shown without a health-reader function, and asks for none of its data", async () => {
    const api = systemRoutes(undefined, { "GET /me": makeMe(["admin.service_health", "admin.data_load"], "super_admin") });
    renderWithClient(<SystemHealth params={{}} />);
    await screen.findAllByTestId(/^card-/);
    expect(screen.queryByRole("region", { name: "Court Calls" })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/admin/napix/calls"))).toBe(false);
  });

  it("the menu child shows with both functions only", async () => {
    browserApi({ "GET /reference/labels": labels() });
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["admin.service_health"], "super_admin")} />);
    expect(screen.queryByRole("treeitem", { name: "Court Calls" })).toBeNull();
    unmount();
    resetNav("/system");
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["admin.service_health", "reports.state"], "super_admin")} />);
    expect(screen.getByRole("treeitem", { name: "Court Calls" })).toHaveAttribute("href", "/system#calls");
  });
});

describe("the four tabs; the old ones redirect (decisions 1-4)", () => {
  it("the Data Collection entry and its tabs follow the functions; Health, Queue and Calls and Duplicates are gone", async () => {
    browserApi({ "GET /reference/labels": labels() });
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["cases.view_scope"])} />);
    expect(screen.queryByRole("treeitem", { name: "Data Collection" })).toBeNull();
    unmount();
    const me = makeMe(["admin.napix_refetch"], "central_operator");
    browserApi({ "GET /reference/labels": labels(), "GET /me": me });
    renderWithClient(
      <>
        <Sidebar me={me} />
        <DataFrame>
          <p>body</p>
        </DataFrame>
      </>,
    );
    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(within(nav).getByRole("treeitem", { name: "Data Collection" })).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("treeitem", { name: "Problems and Fixes" })).toHaveAttribute("aria-current", "page");
    const tabs = await screen.findByRole("navigation", { name: "Data Collection Sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Overview",
      "Collect Now",
      "Automatic Collection",
      "Problems and Fixes",
    ]);
    for (const gone of ["Health", "Queue and Calls", "Duplicates"]) expect(within(tabs).queryByRole("link", { name: gone })).toBeNull();
    expect(within(tabs).getByRole("link", { name: "Problems and Fixes" })).toHaveAttribute("aria-current", "page");
  });

  it("the old addresses land on their new places", () => {
    expect(DATA_TABS.map((t) => t.key)).toEqual(["overview", "collect", "automatic", "problems"]);
    expect(OLD_DATA_REDIRECTS["/data/health"]).toBe("/data/overview");
    expect(OLD_DATA_REDIRECTS["/data/queue"]).toBe("/data/problems");
    expect(OLD_DATA_REDIRECTS["/data/duplicates"]).toBe("/data/problems#duplicates");
  });

  it("a login without a reading function sees no tabs", async () => {
    browserApi({ "GET /me": makeMe(["cases.view_scope"]) });
    renderWithClient(
      <DataFrame>
        <p>body</p>
      </DataFrame>,
    );
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.queryByText("body")).toBeNull();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import type { DataHealth, Duplicates as DuplicatesList, NapixHealth, Permission } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { DataFrame } from "./DataFrame";
import { Duplicates } from "./Duplicates";
import { Health } from "./Health";
import { QueueAndCalls } from "./Queue";

const READER: Permission[] = ["reports.state"];
const OPERATOR: Permission[] = ["admin.napix_refetch", "admin.masters_sync", "reports.state"];
const MANAGER: Permission[] = ["admin.data_load"];

beforeEach(() => {
  resetNav("/data/health");
});

const NAPIX = {
  enabled: false,
  est_code: "GAHC01",
  window: {
    status: "current",
    started_at: "2026-10-11T14:34:30+05:30",
    observed_at: "2026-10-11T14:34:30+05:30",
    next_reset_at: "2026-10-11T15:34:30+05:30",
    seconds_to_next_reset: 1200,
    anchor_at: "2026-10-11T14:34:30+05:30",
    calls: 12,
    failed: 1,
    remaining: 900,
    last_reading_at: "2026-10-11T15:14:00+05:30",
    recent_resets: [
      {
        observed_at: "2026-10-11T14:34:30+05:30",
        previous_at: "2026-10-11T14:34:00+05:30",
        previous_remaining: 769,
        remaining: 999,
        precise: true,
      },
      {
        observed_at: "2026-10-11T12:30:07+05:30",
        previous_at: "2026-10-11T11:30:07+05:30",
        previous_remaining: 148,
        remaining: 999,
        precise: false,
      },
    ],
    window_seconds: 3600,
    margin_seconds: 60,
    probe_seconds: 180,
    reserve: 150,
    live_reserve: 100,
    search_floor: 50,
  },
  today: { calls: 120, failed: 3, by_family: {}, token_unverified: 0 },
  last_call_at: "2026-10-11T10:10:00+05:30",
  last_ok_at: "2026-10-11T10:10:00+05:30",
  last_failure: null,
  last_check: null,
  by_user: null,
} as unknown as NapixHealth;

const BY_USER = {
  window: [{ user_id: "u-1", name: "Rina Das", calls: 4, failed: 0 }],
  today: [
    { user_id: "u-1", name: "Rina Das", calls: 9, failed: 1 },
    { user_id: "u-2", name: "Arup Nath", calls: 2, failed: 0 },
  ],
};

const SNAPSHOT = {
  as_of: "2026-10-11T10:00:00+05:30",
  napix: NAPIX,
  queue: {
    by_kind: [
      {
        kind: "dossier",
        pending: 10,
        runnable: 10,
        waiting: 0,
        running: 0,
        stale: 0,
        failed: 0,
        skipped: 0,
        done: 5,
        by_lane: { request: 1, daily: 2, load: 7 },
      },
    ],
    oldest_runnable_at: null,
    failed_total: 0,
  },
  daily_cycle: [],
  status_batches: null,
  masters: [],
  jobs: [],
  mail: { email_queued: 0, email_failed: 0, email_oldest_queued_at: null, digests_queued: 0, digests_failed: 0 },
  sourcetrace: {},
  failures: [],
  documents_text: {
    order: { pending: 3220, extracted: 57392, failed: 0, none: { scanned_pdf: 0, image: 0, doc: 0, other: 0 } },
    upload: { pending: 0, extracted: 14, failed: 11, none: { scanned_pdf: 12, image: 15, doc: 13, other: 0 } },
    attachment: { pending: 0, extracted: 0, failed: 0, none: { scanned_pdf: 0, image: 16, doc: 0, other: 0 } },
  },
} as unknown as DataHealth;

const QUEUED_DAY = {
  kind: "causelist_day",
  ref: "2025-01-06",
  queue_id: "q",
  status: "pending",
  priority: 20,
  attempts: 0,
  not_before: null,
  lane: "request",
  napix_enabled: false,
};

describe("the health tab", () => {
  function healthRoutes(functions: Permission[], extra: Record<string, unknown> = {}) {
    return browserApi({
      "GET /me": makeMe(functions, "central_operator"),
      "GET /admin/data-health": SNAPSHOT,
      "GET /admin/napix/health": NAPIX,
      ...extra,
    });
  }

  it("keeps only the connectivity check; the re-fetch and reference-list buttons moved to Collect Now", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    expect(await screen.findByRole("heading", { name: "Court Gateway" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connectivity Check" })).toBeNull();
    unmount();
    healthRoutes(["admin.masters_sync", "admin.napix_refetch"]);
    renderWithClient(<Health />);
    expect(await screen.findByRole("button", { name: "Connectivity Check" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync Masters" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-fetch a Day" })).toBeNull();
    expect(await screen.findByText("7")).toBeInTheDocument(); // the load lane's pending dossiers
  });

  it.each([
    ["current", "Current window started about 14:34; next reset about 15:34"],
    ["reset_due", "A new window was due at about 15:34; no call since"],
    ["overdue", "The reset expected at about 15:34 has not been seen; checking every 3 minutes"],
    ["unknown", "Window timing not known yet; it is found at the next call"],
  ])("the window tile names the window (%s)", async (status, text) => {
    const napix = { ...NAPIX, window: { ...NAPIX.window, status } } as NapixHealth;
    healthRoutes(["reports.state"], { "GET /admin/napix/health": napix });
    renderWithClient(<Health />);
    expect(await screen.findByText("This Window")).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("shows the document text block by kind, the ones not read split by type (document-ocr)", async () => {
    healthRoutes(["reports.state"]);
    renderWithClient(<Health />);
    const block = await screen.findByRole("region", { name: "Document Text" });
    expect(within(block).getByText(/not read, so they cannot be searched by their content/)).toBeInTheDocument();
    const rowOf = (name: string) => within(block).getByRole("row", { name: new RegExp(`^${name}`) });
    expect(within(rowOf("Court Orders")).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "Court Orders",
      formatNumber(3220),
      formatNumber(57392),
      "0",
      "0",
      "0",
      "0",
      "0",
    ]);
    expect(within(rowOf("Uploads")).getAllByRole("cell").map((c) => c.textContent)).toEqual(["Uploads", "0", "14", "11", "12", "15", "13", "0"]);
    expect(within(rowOf("Note Attachments")).getAllByRole("cell")[5]).toHaveTextContent("16");
    expect(within(block).getByRole("columnheader", { name: "Scanned PDFs, Not Read" })).toBeInTheDocument();
  });

  it("shows the corrected lists, the recheck and the Retention block (court-data-freshness)", async () => {
    healthRoutes(["reports.state"], {
      "GET /admin/data-health": {
        ...SNAPSHOT,
        daily_cycle: [
          {
            date: "2026-10-11",
            label: "today",
            causelist_day: { status: "done", attempts: 1, finished_at: null, last_error: null },
            lists_stored: 40,
            entries_parsed: 900,
            lists_parse_failed: 0,
            lists_corrected: 2,
            recheck: { status: "done", attempts: 1, finished_at: null, last_error: null, called: 38, versions_new: 2, unparsed: 0 },
          },
        ],
        retention: {
          call_log_keep_days: 730,
          call_log_oldest_at: "2026-10-01T10:00:00+05:30",
          last_purge_at: null,
          last_purge_deleted: null,
          last_purge_status: null,
          call_log_bytes: 5 * 1_048_576,
          responses_bytes: 120 * 1_048_576,
          disposed_refresh: { eligible: 2800, due_now: 100, queued_last_run: 100, last_run_at: "2026-10-11T02:30:00+05:30" },
        },
      },
    });
    renderWithClient(<Health />);
    const cycle = await screen.findByRole("region", { name: "Daily Cycle" });
    expect(within(cycle).getByRole("columnheader", { name: "Corrected" })).toBeInTheDocument();
    expect(within(cycle).getByText("done · 38 checked")).toBeInTheDocument();
    const block = screen.getByRole("region", { name: "Retention" });
    expect(within(block).getByText(/Court call log kept for 730 days/)).toBeInTheDocument();
    expect(within(block).getByText(/No clean-up has run yet/)).toBeInTheDocument();
    expect(within(block).getByText(/Call log 5 MB; court answers 120 MB/)).toBeInTheDocument();
    expect(within(block).getByText(/100 due now/)).toBeInTheDocument();
  });

  it("links to the period report with reports.state only (portal-reports)", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    expect(await screen.findByRole("link", { name: "Period Report" })).toHaveAttribute("href", "/reports/data-health");
    unmount();
    healthRoutes(["admin.napix_refetch"]);
    renderWithClient(<Health />);
    expect(await screen.findByRole("heading", { name: "Court Gateway" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Period Report" })).toBeNull();
  });

  it("lists the recent resets with the precise mark", async () => {
    healthRoutes(["reports.state"]);
    renderWithClient(<Health />);
    const list = await screen.findByRole("region", { name: "Recent Resets" });
    expect(within(list).getByText(/14:34: 769 → 999/)).toBeInTheDocument();
    expect(within(list).getByText(/12:30: 148 → 999/)).toBeInTheDocument();
    expect(within(list).getAllByText("Precise")).toHaveLength(1);
  });

  it("shows calls by user only when the API sends them", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    await screen.findByText("This Window");
    expect(screen.queryByRole("table", { name: "Calls by User" })).toBeNull();
    unmount();
    healthRoutes(OPERATOR, { "GET /admin/napix/health": { ...NAPIX, by_user: BY_USER } });
    renderWithClient(<Health />);
    const table = await screen.findByRole("table", { name: "Calls by User" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1] as HTMLElement).getByText("Rina Das")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("4")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("9")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Arup Nath")).toBeInTheDocument();
  });

});

describe("the call log", () => {
  function call(extra: Record<string, unknown> = {}) {
    return {
      id: "k-1",
      called_at: "2026-10-11T15:10:00+05:30",
      api: "hc-party-name-api/partyname",
      http_status: 200,
      napix_status: null,
      ok: true,
      error_family: null,
      error: null,
      duration_ms: 300,
      token_verified: true,
      rate_limit_remaining: 640,
      job_run_id: null,
      lane: null,
      user_id: null,
      user_name: null,
      ...extra,
    };
  }

  function routes(items: unknown[]) {
    return browserApi({
      "GET /me": makeMe(READER, "central_operator"),
      "GET /admin/napix/queue": { total: 0, items: [] },
      "GET /admin/napix/calls": { items, next_cursor: null },
    });
  }

  it("shows the lane, and the user column only when users are returned", async () => {
    routes([call(), call({ id: "k-2", lane: "load" })]);
    const { unmount } = renderWithClient(<QueueAndCalls />);
    const table = await screen.findByRole("table", { name: "Call Log" });
    expect(within(table).getByRole("columnheader", { name: "Lane" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "User" })).toBeNull();
    expect(within(table).getByText("Searches and Checks")).toBeInTheDocument();
    expect(within(table).getByText("Backdated Load")).toBeInTheDocument();
    unmount();
    routes([call({ lane: "request", user_id: "u-1", user_name: "Rina Das" }), call({ id: "k-2" })]);
    renderWithClient(<QueueAndCalls />);
    const second = await screen.findByRole("table", { name: "Call Log" });
    expect(within(second).getByRole("columnheader", { name: "User" })).toBeInTheDocument();
    expect(within(second).getByText("Rina Das")).toBeInTheDocument();
    expect(within(second).getByText("Requests")).toBeInTheDocument();
  });
});

describe("duplicates", () => {
  const LIST: DuplicatesList = {
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

  it("lists the pairs and scans with admin.data_load only", async () => {
    browserApi({ "GET /me": makeMe(READER), "GET /admin/data-load/duplicates": LIST });
    const { unmount } = renderWithClient(<Duplicates />);
    expect(await screen.findByText("portal records on the provisional case: case_ownership")).toBeInTheDocument();
    expect(screen.getByText("ASLMS/GHC/CASE/2026/000009")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scan Now" })).toBeNull();
    unmount();
    const api = browserApi({
      "GET /me": makeMe(MANAGER),
      "GET /admin/data-load/duplicates": LIST,
      "POST /admin/data-load/duplicates/scan": { merged: 3, needs_review: 1, court_linked: 2 },
    });
    renderWithClient(<Duplicates />);
    await userEvent.click(await screen.findByRole("button", { name: "Scan Now" }));
    expect(await screen.findByText("3 merged, 1 listed for review, 2 court duplicates linked.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Merged" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("kind=merged"))).toBe(true));
  });
});

describe("navigation", () => {
  it("the Data collection entry and its tabs follow the functions", async () => {
    browserApi({ "GET /reference/labels": labels() });
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["cases.view_scope"])} />);
    expect(screen.queryByRole("treeitem", { name: "Data Collection" })).toBeNull();
    unmount();
    resetNav("/data/health");
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
    // design portal-ui-polish-2, decision 16: the entry opens on its pages and the page's child is current
    expect(within(nav).getByRole("treeitem", { name: "Data Collection" })).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("treeitem", { name: "Health" })).toHaveAttribute("aria-current", "page");
    const tabs = await screen.findByRole("navigation", { name: "Data Collection Sections" });
    for (const name of ["Overview", "Collect Now", "Automatic Collection", "Health", "Queue and Calls", "Duplicates"]) {
      expect(within(tabs).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(tabs).getByRole("link", { name: "Health" })).toHaveAttribute("aria-current", "page");
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

describe("the Dashboard template (design portal-ui-redesign, decision 26)", () => {
  it("the health tab puts the call counts in headline numbers and has no primary", async () => {
    browserApi({
      "GET /me": makeMe(["reports.state", "admin.napix_refetch", "admin.masters_sync"], "central_operator"),
      "GET /admin/data-health": SNAPSHOT,
      "GET /admin/napix/health": NAPIX,
    });
    const { container } = renderWithClient(<Health />);
    const gateway = await screen.findByRole("region", { name: "Court Gateway" });
    expect(within(gateway).getAllByText(/./, { selector: "[class*='kpiLabel']" }).length).toBe(2);
    expect(screen.getByRole("region", { name: "Document Text" }).className).toMatch(/wide/);
    expect(primaryActions(container)).toEqual([]);
  });

  it("the duplicate kinds are chips, not primary buttons", async () => {
    browserApi({
      "GET /me": makeMe(["admin.data_load"], "central_operator"),
      "GET /admin/data-load/duplicates": { items: [], total: 0 },
    });
    const { container } = renderWithClient(<Duplicates />);
    const group = await screen.findByRole("group", { name: "Duplicates" });
    expect(within(group).getByRole("button", { name: "Needs Review" })).toHaveAttribute("aria-pressed", "true");
    expect(primaryActions(container)).toEqual([]);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("Health renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(OPERATOR, "central_operator"),
      "GET /admin/data-health": SNAPSHOT,
      "GET /admin/napix/health": { ...NAPIX, by_user: BY_USER },
    });
    renderWithClient(<Health />);
    expectDataTable(await screen.findByRole("table", { name: "Calls by User" }));
    expectDataTable(screen.getByRole("table", { name: "Queue" }));
    expectDataTable(screen.getByRole("table", { name: "Document Text" }));
  });

  it("Queue renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(READER, "central_operator"),
      "GET /admin/napix/queue": { total: 1, items: [{ id: "q-1", ...QUEUED_DAY, last_error: "NapixUnavailable: 503", status: "failed" }] },
      "GET /admin/napix/calls": {
        items: [{ id: "k-1", called_at: "2026-10-11T15:10:00+05:30", api: "hc-cnr-api/cnr", http_status: 200, ok: true, lane: "load", user_name: null }],
        next_cursor: null,
      },
    });
    renderWithClient(<QueueAndCalls />);
    expectDataTable(await screen.findByRole("table", { name: "Queue Rows" }));
    expectDataTable(await screen.findByRole("table", { name: "Call Log" }));
  });

  it("Duplicates renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(READER),
      "GET /admin/data-load/duplicates": {
        total: 1,
        items: [
          {
            kind: "review",
            case: { id: "p", ref_no: "ASLMS/GHC/CASE/2026/000009", cnr: null, case_no_text: "WPC/3600/2026" },
            other: { id: "c", ref_no: "ASLMS/GHC/CASE/2026/000002", cnr: "GAHC010129772026", case_no_text: "WP(C)/3600/2026" },
            at: "2026-10-11T03:00:00+05:30",
            reasons: "portal records on the provisional case",
          },
        ],
      },
    });
    renderWithClient(<Duplicates />);
    await screen.findByText("portal records on the provisional case");
    expectDataTable(screen.getByRole("table"));
  });
});


describe("Layout B on the Queue (portal-ui-polish-2, decision 23)", () => {
  it("Reference Starts With is the hero, applied by Search; Kind, Status and Lane apply at once; the strip counts the rows", async () => {
    const api = browserApi({
      "GET /me": makeMe(READER, "central_operator"),
      "GET /admin/napix/queue": { total: 7, items: [{ id: "q-1", ...QUEUED_DAY, last_error: null, status: "pending" }] },
      "GET /admin/napix/calls": { items: [], next_cursor: null },
    });
    const { container } = renderWithClient(<QueueAndCalls />);
    const hero = container.querySelector<HTMLElement>("[data-zone='hero']")!;
    const fields = container.querySelector<HTMLElement>("[data-zone='fields']")!;
    for (const label of ["Kind", "Status", "Lane"]) expect(within(fields).getByLabelText(label)).toBeInTheDocument();
    const strip = await waitFor(() => {
      const el = container.querySelector<HTMLElement>("[data-zone='summary']");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(strip).toHaveTextContent("1 of 7 rows shown");
    const queueCalls = () => api.calls.filter((c) => c.path.startsWith("/admin/napix/queue"));
    await userEvent.type(within(hero).getByLabelText("Reference Starts With"), "2026-10");
    expect(queueCalls().some((c) => c.url.includes("ref=2026-10"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(queueCalls().some((c) => c.url.includes("ref=2026-10"))).toBe(true));
    await userEvent.selectOptions(within(fields).getByLabelText("Lane"), "load");
    await waitFor(() => expect(queueCalls().some((c) => c.url.includes("lane=load") && c.url.includes("ref=2026-10"))).toBe(true));
  });
});

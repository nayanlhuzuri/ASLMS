import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import type { DataHealth, DataLoad, Duplicates as DuplicatesList, NapixHealth, Permission } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, labels, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { DataFrame } from "./DataFrame";
import { Discovery } from "./Discovery";
import { Duplicates } from "./Duplicates";
import { Health } from "./Health";
import { LoadConsole } from "./LoadConsole";
import { QueueAndCalls } from "./Queue";

function progress(extra: Partial<DataLoad> = {}): DataLoad {
  return {
    as_of: "2026-10-11T10:00:00+05:30",
    napix_enabled: false,
    settings: {
      version: 2,
      paused: false,
      load_order: "cases_first",
      first_from: null,
      first_to: null,
      reason: "resumed",
      changed_at: "2026-10-11T09:00:00+05:30",
      changed_by: "Super Administrator",
    },
    period: { from: "2025-01-01", to: "2025-12-31" },
    totals: {
      days: { calendar: 365, with_lists: 200, no_list: 60, waiting: 100, failed: 5, not_queued: 0 },
      cases: { listed: 9000, with_details: 4000, provisional: 300 },
      orders: { referenced: 20000, stored: 5000, not_available: 100, waiting: 14900 },
    },
    work_left: [
      { kind: "causelist_day", pending: 100, runnable: 90, waiting: 10, running: 1, failed: 5 },
      { kind: "dossier", pending: 5000, runnable: 5000, waiting: 0, running: 0, failed: 0 },
      { kind: "order_pdf", pending: 14900, runnable: 14900, waiting: 0, running: 0, failed: 2 },
    ],
    failures: {
      by_kind: [
        { kind: "causelist_day", failed: 5 },
        { kind: "order_pdf", failed: 2 },
      ],
      latest: [
        {
          id: "f-1",
          kind: "causelist_day",
          ref: "2025-03-04",
          attempts: 5,
          last_error: "IntegrationError: 502",
          finished_at: "2026-10-11T08:00:00+05:30",
        },
      ],
    },
    allowance: {
      window_started_at: "2026-10-11T14:34:30+05:30",
      next_reset_at: "2026-10-11T15:34:30+05:30",
      seconds_to_next_reset: 1800,
      window_status: "current",
      used: { load: 300, daily: 40, request: 5, outside_queue: 3 },
      remaining: 652,
      rate_reserve: 150,
      live_reserve: 100,
      search_floor: 50,
    },
    estimate: {
      finish_at: "2026-10-20T10:00:00+05:30",
      hours: 216,
      calls_needed: 108000,
      reason: null,
      basis: { calls_per_hour: 500 },
    },
    ...extra,
  } as DataLoad;
}

const READER: Permission[] = ["reports.state"];
const OPERATOR: Permission[] = ["admin.napix_refetch", "admin.masters_sync", "reports.state"];
const MANAGER: Permission[] = ["admin.data_load"];

function consoleRoutes(functions: Permission[], extra: Record<string, unknown> = {}, data: DataLoad = progress()) {
  return browserApi({
    "GET /me": makeMe(functions, "central_operator"),
    "GET /admin/data-load": data,
    ...extra,
  });
}

beforeEach(() => {
  resetNav("/data/load");
});

describe("the load console", () => {
  it("renders the status, allowance by lane, work left and the estimate", async () => {
    consoleRoutes(READER);
    renderWithClient(<LoadConsole />);
    expect(await screen.findByText("The backdated load is running.")).toBeInTheDocument();
    expect(screen.getByText(/Load period 1 Jan 2025 to 31 Dec 2025/)).toBeInTheDocument();
    expect(screen.getByText("652 calls remaining")).toBeInTheDocument();
    expect(screen.getByText("Backdated load")).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText(/About 20 Oct 2026, 10:00 \(216 hours\)/)).toBeInTheDocument();
    expect(screen.getByText("The court gateway is off for this server.", { exact: false })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Work left" });
    expect(within(table).getByText("Case details")).toBeInTheDocument();
    expect(screen.getByText("IntegrationError: 502")).toBeInTheDocument();
  });

  it.each([
    ["current", "Current window started about 14:34; next reset about 15:34"],
    ["reset_due", "A new window was due at about 15:34; no call since"],
    ["overdue", "The reset expected at about 15:34 has not been seen; checking every 3 minutes"],
    ["unknown", "Window timing not known yet; it is found at the next call"],
  ])("the allowance card names the window (%s)", async (status, text) => {
    const data = progress();
    data.allowance = { ...data.allowance, window_status: status as DataLoad["allowance"]["window_status"] };
    if (status === "unknown") data.allowance = { ...data.allowance, remaining: null, next_reset_at: null };
    consoleRoutes(READER, {}, data);
    renderWithClient(<LoadConsole />);
    expect(await screen.findByRole("heading", { name: "Court gateway allowance, this window" })).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    if (status === "unknown") expect(screen.getByText("No call in this window yet.")).toBeInTheDocument();
  });

  it.each([
    ["paused", "No estimate while the load is paused."],
    ["not_enough_history", "No estimate yet: less than a day of load history."],
    ["no_recent_calls", /no load call in the last hour/],
  ])("explains why there is no estimate (%s)", async (reason, text) => {
    const data = progress();
    data.estimate = { finish_at: null, hours: null, calls_needed: null, reason, basis: {} };
    consoleRoutes(READER, {}, data);
    renderWithClient(<LoadConsole />);
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("shows actions only with admin.data_load and retry only with admin.napix_refetch", async () => {
    consoleRoutes(READER);
    const { unmount } = renderWithClient(<LoadConsole />);
    await screen.findByText("The backdated load is running.");
    expect(screen.queryByRole("heading", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retry failed/ })).toBeNull();
    unmount();

    consoleRoutes(OPERATOR);
    const second = renderWithClient(<LoadConsole />);
    await screen.findByText("The backdated load is running.");
    expect(await screen.findByRole("button", { name: "Retry failed: Cause-list days" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Actions" })).toBeNull();
    second.unmount();

    consoleRoutes(MANAGER);
    renderWithClient(<LoadConsole />);
    expect(await screen.findByRole("heading", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Start a load" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry failed/ })).toBeNull();
  });

  it("retries the failed rows of one kind in the load lane", async () => {
    const api = consoleRoutes(OPERATOR, { "POST /admin/napix/queue/retry-failed": { kind: "order_pdf", retried: 2 } });
    renderWithClient(<LoadConsole />);
    await userEvent.click(await screen.findByRole("button", { name: "Retry failed: Order PDFs" }));
    expect(await screen.findByText("2 rows queued again.")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "/admin/napix/queue/retry-failed");
    expect(call?.body).toEqual({ kind: "order_pdf", lane: "load" });
  });

  it("start: preview, then the choice for held days, then start", async () => {
    const api = consoleRoutes(MANAGER, {
      "POST /admin/data-load/preview": {
        days: 10,
        held_with_lists: 2,
        held_no_list: 1,
        waiting: 2,
        failed: 2,
        not_queued: 3,
        calls_estimate: null,
        masters_stale: true,
      },
      "POST /admin/data-load/start": { days: 10, queued: 3, held_skipped: 0, held_requeued: 3, revived: 2, masters_queued: true },
    });
    renderWithClient(<LoadConsole />);
    const form = await screen.findByRole("form", { name: "Start a load" });
    await userEvent.type(within(form).getByLabelText("From"), "2025-02-01");
    await userEvent.type(within(form).getByLabelText("To"), "2025-02-10");
    await userEvent.click(within(form).getByRole("button", { name: "Preview" }));
    expect(await within(form).findByText(/10 days: 3 already held, 2 waiting, 2 failed, 3 not queued/)).toBeInTheDocument();
    expect(within(form).getByText("The masters are older than a day and will be synced first.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/admin/data-load/start")).toBe(false);
    await userEvent.selectOptions(within(form).getByLabelText(/already in the database/), "refetch");
    await userEvent.click(within(form).getByRole("button", { name: "Start" }));
    expect(await within(form).findByText("8 days queued.")).toBeInTheDocument();
    const start = api.calls.find((c) => c.path === "/admin/data-load/start");
    expect(start?.body).toEqual({ from: "2025-02-01", to: "2025-02-10", held: "refetch" });
  });

  it("pause needs a reason", async () => {
    const api = consoleRoutes(MANAGER, { "POST /admin/data-load/pause": progress().settings });
    renderWithClient(<LoadConsole />);
    const form = await screen.findByRole("form", { name: "Pause" });
    const button = within(form).getByRole("button", { name: "Pause" });
    expect(button).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Why pause the load?"), "quota for searches");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await waitFor(() => expect(api.calls.some((c) => c.path === "/admin/data-load/pause")).toBe(true));
    expect(api.calls.find((c) => c.path === "/admin/data-load/pause")?.body).toEqual({ reason: "quota for searches" });
  });
});

describe("fetching from the court", () => {
  const held = {
    case: {
      id: "c-1",
      ref_no: "ASLMS/GOA/CASE/2026/000001",
      cnr: "GAHC010129772026",
      case_no_text: "WP(C)/3600/2026",
      is_provisional: false,
      petitioner_summary: null,
      respondent_summary: null,
      status: "pending",
      next_hearing_date: null,
      last_listed_on: null,
    },
    visible: false,
    owner_office_code: null,
    in_pool: true,
    claimable: false,
    match: "held",
    dossier_status: "fetched",
    dossier_fetched_at: "2026-10-08T10:00:00+05:30",
    dossier_stale: false,
  };

  it("already held: Fetch anyway resends with force; Cancel sends nothing", async () => {
    const api = consoleRoutes(MANAGER, {
      "POST /admin/data-load/fetch": (call: { body: unknown }) =>
        (call.body as { force: boolean }).force
          ? { source: "court", calls: 1, created: 0, items: [held], unmatched: [] }
          : json(409, { detail: { code: "already_held", message: "held", cases: [held] } }),
    });
    renderWithClient(<LoadConsole />);
    const form = await screen.findByRole("form", { name: "Fetch from the court" });
    await userEvent.type(within(form).getByLabelText("CNR"), "gahc010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const dialog = await screen.findByRole("dialog", { name: "Already in the database" });
    expect(within(dialog).getByText(/ASLMS\/GOA\/CASE\/2026\/000001: details fetched 8 Oct 2026/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.calls.filter((c) => c.path === "/admin/data-load/fetch")).toHaveLength(1);

    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const again = await screen.findByRole("dialog", { name: "Already in the database" });
    await userEvent.click(within(again).getByRole("button", { name: "Fetch anyway" }));
    expect(await screen.findByText(/not visible to you/)).toBeInTheDocument();
    const sent = api.calls.filter((c) => c.path === "/admin/data-load/fetch").map((c) => c.body);
    expect(sent).toEqual([
      { kind: "cnr", cnr: "GAHC010129772026", force: false },
      { kind: "cnr", cnr: "GAHC010129772026", force: false },
      { kind: "cnr", cnr: "GAHC010129772026", force: true },
    ]);
  });

  it("searched before: the dialog names when, and the results can be queued for details", async () => {
    const found = { ...held, visible: true, dossier_status: "none" };
    const api = consoleRoutes(MANAGER, {
      "POST /admin/data-load/fetch": (call: { body: unknown }) =>
        (call.body as { force: boolean }).force
          ? { source: "court", calls: 1, created: 1, items: [found], unmatched: [] }
          : json(409, {
              detail: {
                code: "searched_before",
                message: "searched",
                last_searched_at: "2026-10-10T11:00:00+05:30",
                stored: 4,
                local_matches: 2,
              },
            }),
      "POST /admin/data-load/fetch-details": {
        items: [{ ref: "ASLMS/GOA/CASE/2026/000001", case: found, state: "queued", queue: null }],
      },
    });
    renderWithClient(<LoadConsole />);
    const form = await screen.findByRole("form", { name: "Fetch from the court" });
    await userEvent.selectOptions(within(form).getByLabelText("Search by"), "party");
    await userEvent.type(within(form).getByLabelText("Party name"), "RAMEN DAS");
    await userEvent.type(within(form).getByLabelText("Year"), "2026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const dialog = await screen.findByRole("dialog", { name: "Searched before" });
    expect(within(dialog).getByText(/10 Oct 2026, 11:00 \(4 cases stored\). 2 held cases match locally./)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Fetch anyway" }));
    const box = await screen.findByRole("checkbox", { name: "ASLMS/GOA/CASE/2026/000001" });
    const details = screen.getByRole("button", { name: "Fetch details" });
    expect(details).toBeDisabled();
    await userEvent.click(box);
    await userEvent.click(details);
    expect(await screen.findByText("1 cases queued for details.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/admin/data-load/fetch-details")?.body).toEqual({
      cases: ["ASLMS/GOA/CASE/2026/000001"],
      force: false,
    });
  });
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

  it("shows each button by its function", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    expect(await screen.findByRole("heading", { name: "Court gateway" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync masters" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-fetch a day" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Connectivity check" })).toBeNull();
    unmount();
    healthRoutes(["admin.masters_sync"]);
    const second = renderWithClient(<Health />);
    expect(await screen.findByRole("button", { name: "Sync masters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connectivity check" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-fetch a day" })).toBeNull();
    second.unmount();
    healthRoutes(["admin.napix_refetch"]);
    renderWithClient(<Health />);
    expect(await screen.findByRole("button", { name: "Re-fetch a day" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync masters" })).toBeNull();
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
    expect(await screen.findByText("This window")).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("shows the document text block by kind, the ones not read split by type (document-ocr)", async () => {
    healthRoutes(["reports.state"]);
    renderWithClient(<Health />);
    const block = await screen.findByRole("region", { name: "Document text" });
    expect(within(block).getByText(/not read, so they cannot be searched by their content/)).toBeInTheDocument();
    const rowOf = (name: string) => within(block).getByRole("row", { name: new RegExp(`^${name}`) });
    expect(within(rowOf("Court orders")).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "Court orders",
      formatNumber(3220),
      formatNumber(57392),
      "0",
      "0",
      "0",
      "0",
      "0",
    ]);
    expect(within(rowOf("Uploads")).getAllByRole("cell").map((c) => c.textContent)).toEqual(["Uploads", "0", "14", "11", "12", "15", "13", "0"]);
    expect(within(rowOf("Note attachments")).getAllByRole("cell")[5]).toHaveTextContent("16");
    expect(within(block).getByRole("columnheader", { name: "Scanned PDFs, not read" })).toBeInTheDocument();
  });

  it("links to the period report with reports.state only (portal-reports)", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    expect(await screen.findByRole("link", { name: "Period report" })).toHaveAttribute("href", "/reports/data-health");
    unmount();
    healthRoutes(["admin.napix_refetch"]);
    renderWithClient(<Health />);
    expect(await screen.findByRole("heading", { name: "Court gateway" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Period report" })).toBeNull();
  });

  it("lists the recent resets with the precise mark", async () => {
    healthRoutes(["reports.state"]);
    renderWithClient(<Health />);
    const list = await screen.findByRole("region", { name: "Recent resets" });
    expect(within(list).getByText(/14:34: 769 → 999/)).toBeInTheDocument();
    expect(within(list).getByText(/12:30: 148 → 999/)).toBeInTheDocument();
    expect(within(list).getAllByText("precise")).toHaveLength(1);
  });

  it("shows calls by user only when the API sends them", async () => {
    healthRoutes(["reports.state"]);
    const { unmount } = renderWithClient(<Health />);
    await screen.findByText("This window");
    expect(screen.queryByRole("table", { name: "Calls by user" })).toBeNull();
    unmount();
    healthRoutes(OPERATOR, { "GET /admin/napix/health": { ...NAPIX, by_user: BY_USER } });
    renderWithClient(<Health />);
    const table = await screen.findByRole("table", { name: "Calls by user" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1] as HTMLElement).getByText("Rina Das")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("4")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("9")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("Arup Nath")).toBeInTheDocument();
  });

  it("warns before re-fetching a day already held and resends with force", async () => {
    const api = healthRoutes(["admin.napix_refetch"], {
      "POST /admin/napix/refetch/day": (call: { body: unknown }) =>
        (call.body as { force?: boolean }).force
          ? QUEUED_DAY
          : json(409, { detail: { code: "already_held", message: "held", status: "done", lists_stored: 2, finished_at: null } }),
    });
    renderWithClient(<Health />);
    const form = await screen.findByRole("form", { name: "Re-fetch a day" });
    await userEvent.type(within(form).getByLabelText("Date"), "2025-01-06");
    await userEvent.click(within(form).getByRole("button", { name: "Re-fetch a day" }));
    const dialog = await screen.findByRole("dialog", { name: "Already in the database" });
    expect(within(dialog).getByText("That day is already held (done, 2 lists stored).")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Fetch anyway" }));
    expect(await screen.findByText("Cause-list days queued (pending).")).toBeInTheDocument();
    const bodies = api.calls.filter((c) => c.path === "/admin/napix/refetch/day").map((c) => c.body);
    expect(bodies).toEqual([{ date: "2025-01-06" }, { date: "2025-01-06", force: true }]);
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
    const table = await screen.findByRole("table", { name: "Call log" });
    expect(within(table).getByRole("columnheader", { name: "Lane" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "User" })).toBeNull();
    expect(within(table).getByText("Searches and checks")).toBeInTheDocument();
    expect(within(table).getByText("Backdated load")).toBeInTheDocument();
    unmount();
    routes([call({ lane: "request", user_id: "u-1", user_name: "Rina Das" }), call({ id: "k-2" })]);
    renderWithClient(<QueueAndCalls />);
    const second = await screen.findByRole("table", { name: "Call log" });
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
        case: { id: "p", ref_no: "ASLMS/GOA/CASE/2026/000009", cnr: null, case_no_text: "WPC/3600/2026" },
        other: { id: "c", ref_no: "ASLMS/GOA/CASE/2026/000002", cnr: "GAHC010129772026", case_no_text: "WP(C)/3600/2026" },
        at: "2026-10-11T03:00:00+05:30",
        reasons: "portal records on the provisional case: case_ownership",
      },
    ],
  };

  it("lists the pairs and scans with admin.data_load only", async () => {
    browserApi({ "GET /me": makeMe(READER), "GET /admin/data-load/duplicates": LIST });
    const { unmount } = renderWithClient(<Duplicates />);
    expect(await screen.findByText("portal records on the provisional case: case_ownership")).toBeInTheDocument();
    expect(screen.getByText("ASLMS/GOA/CASE/2026/000009")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scan now" })).toBeNull();
    unmount();
    const api = browserApi({
      "GET /me": makeMe(MANAGER),
      "GET /admin/data-load/duplicates": LIST,
      "POST /admin/data-load/duplicates/scan": { merged: 3, needs_review: 1, court_linked: 2 },
    });
    renderWithClient(<Duplicates />);
    await userEvent.click(await screen.findByRole("button", { name: "Scan now" }));
    expect(await screen.findByText("3 merged, 1 listed for review, 2 court duplicates linked.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Merged" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("kind=merged"))).toBe(true));
  });
});

describe("navigation", () => {
  it("the Data collection entry and its tabs follow the functions", async () => {
    browserApi({ "GET /reference/labels": labels() });
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["cases.view_scope"])} />);
    expect(screen.queryByRole("link", { name: "Data collection" })).toBeNull();
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
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Data collection" })).toHaveAttribute("aria-current", "page");
    const tabs = await screen.findByRole("navigation", { name: "Data collection sections" });
    for (const name of ["Load", "Health", "Queue and calls", "Duplicates"]) {
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
  it("the console shows the lanes as headline numbers, each block a panel, and no primary until a preview", async () => {
    consoleRoutes([...MANAGER, "admin.napix_refetch"], {
      "POST /admin/data-load/preview": {
        days: 2,
        held_with_lists: 0,
        held_no_list: 0,
        waiting: 0,
        failed: 0,
        not_queued: 2,
        calls_estimate: 4,
        masters_stale: false,
      },
    });
    const { container } = renderWithClient(<LoadConsole />);
    const allowance = await screen.findByRole("region", { name: "Court gateway allowance, this window" });
    expect(allowance.className).toMatch(/panel/);
    expect(within(allowance).getAllByText(/./, { selector: "[class*='kpiLabel']" }).length).toBe(5);
    for (const name of ["Status", "Work left", "Estimated finish", "Actions"]) {
      expect(screen.getByRole("region", { name }).className).toMatch(/panel/);
    }
    expect(primaryActions(container)).toEqual([]);
    const form = screen.getByRole("form", { name: "Start a load" });
    await userEvent.type(within(form).getByLabelText("From"), "2025-02-01");
    await userEvent.type(within(form).getByLabelText("To"), "2025-02-02");
    await userEvent.click(within(form).getByRole("button", { name: "Preview" }));
    await within(form).findByRole("button", { name: "Start" });
    expect(primaryActions(container)).toEqual(["Start"]);
  });

  it("the health tab puts the call counts in headline numbers and has no primary", async () => {
    browserApi({
      "GET /me": makeMe(["reports.state", "admin.napix_refetch", "admin.masters_sync"], "central_operator"),
      "GET /admin/data-health": SNAPSHOT,
      "GET /admin/napix/health": NAPIX,
    });
    const { container } = renderWithClient(<Health />);
    const gateway = await screen.findByRole("region", { name: "Court gateway" });
    expect(within(gateway).getAllByText(/./, { selector: "[class*='kpiLabel']" }).length).toBe(2);
    expect(screen.getByRole("region", { name: "Document text" }).className).toMatch(/wide/);
    expect(primaryActions(container)).toEqual([]);
  });

  it("the duplicate kinds are chips, not primary buttons", async () => {
    browserApi({
      "GET /me": makeMe(["admin.data_load"], "central_operator"),
      "GET /admin/data-load/duplicates": { items: [], total: 0 },
    });
    const { container } = renderWithClient(<Duplicates />);
    const group = await screen.findByRole("group", { name: "Duplicates" });
    expect(within(group).getByRole("button", { name: "Needs review" })).toHaveAttribute("aria-pressed", "true");
    expect(primaryActions(container)).toEqual([]);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("LoadConsole renders a DataTable with a primary cell", async () => {
    consoleRoutes(READER);
    renderWithClient(<LoadConsole />);
    expectDataTable(await screen.findByRole("table", { name: "Work left" }));
    expectDataTable(screen.getByRole("table", { name: "Latest failures" }));
  });

  it("Health renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(OPERATOR, "central_operator"),
      "GET /admin/data-health": SNAPSHOT,
      "GET /admin/napix/health": { ...NAPIX, by_user: BY_USER },
    });
    renderWithClient(<Health />);
    expectDataTable(await screen.findByRole("table", { name: "Calls by user" }));
    expectDataTable(screen.getByRole("table", { name: "Queue" }));
    expectDataTable(screen.getByRole("table", { name: "Document text" }));
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
    expectDataTable(await screen.findByRole("table", { name: "Queue rows" }));
    expectDataTable(await screen.findByRole("table", { name: "Call log" }));
  });

  it("Duplicates renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": makeMe(READER),
      "GET /admin/data-load/duplicates": {
        total: 1,
        items: [
          {
            kind: "review",
            case: { id: "p", ref_no: "ASLMS/GOA/CASE/2026/000009", cnr: null, case_no_text: "WPC/3600/2026" },
            other: { id: "c", ref_no: "ASLMS/GOA/CASE/2026/000002", cnr: "GAHC010129772026", case_no_text: "WP(C)/3600/2026" },
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

  it("Discovery renders a DataTable with a primary cell", async () => {
    resetNav("/data/discovery");
    browserApi({
      "GET /me": makeMe(["reports.state"], "state_oversight"),
      "GET /admin/discovery": {
        settings: { share: 100, from_year: 2025 },
        window: { status: "current", started_at: null, next_reset_at: null, discovery_calls: 12, share_left: 88 },
        queue: {
          by_kind: {
            party_search: { pending: 4, waiting: 1, running: 0, failed: 1 },
            dossier: { pending: 3, waiting: 0, running: 1, failed: 0 },
            order_pdf: { pending: 0, waiting: 0, running: 0, failed: 0 },
          },
        },
        terms: { active: 3, inactive: 1 },
        cases: { found: 9, created_by_discovery: 4, recommended_from_discovery: 2 },
        last_searched_at: null,
        latest_failures: [{ kind: "party_search", ref: "GAHC01|P|2025|PRITAM SAIKIA", last_error: "NapixUnavailable: 503", finished_at: null }],
      },
    });
    renderWithClient(<Discovery />);
    await screen.findByText("GAHC01|P|2025|PRITAM SAIKIA");
    for (const table of screen.getAllByRole("table")) expectDataTable(table);
    expect(screen.getAllByRole("table")).toHaveLength(2);
  });
});

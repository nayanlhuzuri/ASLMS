/**
 * Data Collection redesign, round 1 (design data-collection-redesign): Overview (tiles with honest bars, the Problems
 * line, Right Now, the estimate in words, Month by Month, the polling rhythm), Automatic Collection (one primary, the
 * Start, Pause and What Goes First dialogs and forms, Calls by Person only when sent, the schedule) and Collect Now
 * (today's forms moved unchanged, each card by its function), and the frame (`/data` opens Overview; a `stack`).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { Coverage, DataLoad, Permission } from "@/lib/api/types";
import { DC_KEYS, POLL, type DataOverview, type DataPulse, type DataSchedule } from "@/lib/dataCollection";
import { formatNumber as f } from "@/lib/format";
import { nav as navState, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { AutomaticCollection } from "./AutomaticCollection";
import { CollectNow } from "./CollectNow";
import { DataFrame, DataIndex } from "./DataFrame";
import { Overview } from "./Overview";

const READER: Permission[] = ["reports.state"];
const OPERATOR: Permission[] = ["admin.napix_refetch", "admin.masters_sync", "reports.state"];
const MANAGER: Permission[] = ["admin.data_load"];

function progress(): DataLoad {
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
    totals: null,
    work_left: [
      { kind: "causelist_day", pending: 100, runnable: 90, waiting: 10, running: 1, failed: 5 },
      { kind: "dossier", pending: 5000, runnable: 5000, waiting: 0, running: 0, failed: 0 },
      { kind: "order_pdf", pending: 14900, runnable: 14900, waiting: 0, running: 0, failed: 2 },
    ],
    failures: { by_kind: [], latest: [] },
    allowance: {
      window_started_at: "2026-10-11T14:34:30+05:30",
      next_reset_at: "2026-10-11T15:34:30+05:30",
      seconds_to_next_reset: 1800,
      window_status: "current",
      used: { load: 300, discovery: 0, daily: 40, request: 5, outside_queue: 3 },
      remaining: 652,
      rate_reserve: 150,
      live_reserve: 100,
      search_floor: 50,
    },
    estimate: { finish_at: null, hours: null, calls_needed: null, reason: null, basis: { calls_per_hour: 500 } },
  } as DataLoad;
}

const OVERVIEW = {
  as_of: "2026-10-26T10:00:00+05:30",
  napix_enabled: false,
  settings: progress().settings,
  collection: "running",
  period: { from: "2025-01-01", to: "2026-09-29" },
  position: { working_on: "2026-01-05", working_on_month: "2026-01" },
  days: { calendar: 664, with_lists: 280, no_list: 26, waiting: 267, failed: 3, not_queued: 88, collected: 306, to: "2026-10-26" },
  cases: { found: 59033, with_details: 58924, without_details: 109, provisional: 12 },
  orders: {
    referenced: 320869,
    stored: 137932,
    waiting: 182929,
    not_available: 8,
    failed: 0,
    in_period: { referenced: 300000, stored: 130000, waiting: 169992, not_available: 8, failed: 0 },
  },
  left: { causelist_days: 267, case_details: 33, order_pdfs: 182929, other: 2, total: 183231 },
  waiting_work: [
    { kind: "causelist_day", total: 266, by_lane: { request: 0, daily: 0, discovery: 0, load: 266 }, running: 1, failed: 3 },
    { kind: "order_pdf", total: 182928, by_lane: { request: 10, daily: 167388, discovery: 0, load: 15530 }, running: 1, failed: 0 },
  ],
  problems: { failed: 12, duplicates_review: 3, cases_without_details: 109, orders_not_available: 8, orders_failed: 0 },
  estimate: {
    details: { finish_at: "2026-10-28T09:00:00+05:30", hours: 36, calls_needed: 29520, reason: null },
    all: { finish_at: "2026-11-08T09:00:00+05:30", hours: 312, calls_needed: 255840, reason: null },
    basis: {
      window_days: 7,
      calls_per_item: { causelist_day: 3.1, dossier: 1.2, order_pdf: 1 },
      finished: { causelist_day: 40, dossier: 900, order_pdf: 9000 },
      calls: { causelist_day: 124, dossier: 1080, order_pdf: 9000 },
      dossiers_per_day: 110.5,
      pdfs_per_dossier: 5.2,
      calls_per_hour: 820.4,
      pending: { causelist_day: 267, dossier: 33, order_pdf: 182929 },
      history_hours: 400,
      calls_last_hour: 870,
      hourly_limit: 1000,
    },
  },
  bulk: null,
} as DataOverview;

const PULSE: DataPulse = {
  as_of: "2026-10-26T10:00:00+05:30",
  napix_enabled: false,
  window: {
    status: "current",
    remaining: 360,
    used: 640,
    hourly_limit: 1000,
    next_reset_at: "2026-10-26T10:12:00+05:30",
    seconds_to_next_reset: 720,
  },
  queue: [{ kind: "order_pdf", pending: 182928, running: 1 }],
  running: [{ kind: "order_pdf", lane: "daily", started_at: "2026-10-26T09:59:58+05:30" }],
  calls_last_5_min: 70,
  last_call_at: "2026-10-26T09:59:59+05:30",
  requests_active: 2,
};

function month(m: string, state: string, extra: Record<string, unknown> = {}) {
  return {
    month: m,
    days: { calendar: 31, with_lists: 26, no_list: 5, waiting: 0, failed: 0, not_queued: 0 },
    lists: 412,
    entries: 18220,
    lists_parse_failed: 0,
    cases: { listed: 4130, with_details: 4120, provisional: 3, without_details: 10, queued: 10, failed: 0 },
    orders: { referenced: 9876, stored: 2978, not_available: 0, waiting: 6898, failed: 0 },
    work_left: { causelist_day: 0, dossier: 0, order_pdf: 0 },
    failed: { causelist_day: 0, dossier: 0, order_pdf: 0 },
    days_covered_pct: 100,
    details_pct: 99.8,
    left: { days: 0, cases: 10, order_pdfs: 6898 },
    state,
    ...extra,
  };
}

const COVERAGE = {
  months: [
    month("2025-01", "done"),
    month("2026-03", "not_reached", {
      days: { calendar: 31, with_lists: 0, no_list: 0, waiting: 31, failed: 0, not_queued: 0 },
      left: { days: 31, cases: 0, order_pdfs: 40 },
    }),
  ],
  earlier_orders: { referenced: 12, stored: 2, not_available: 0, waiting: 10, failed: 0 },
  position: { working_on: "2026-01-05", working_on_month: "2026-01" },
} as unknown as Coverage;

const SCHEDULE: DataSchedule = {
  entries: [
    { key: "masters", when: "06:00", what: "Update the court's reference lists", last_run_at: null, result: null, facts: {} },
    {
      key: "disposed-refresh",
      when: "02:30",
      what: "Refresh cases disposed in the last year, monthly",
      last_run_at: "2026-10-26T02:30:00+05:30",
      result: "succeeded",
      facts: { eligible: 1234, due_now: 56 },
    },
    {
      key: "purge",
      when: "03:45",
      what: "Remove court call records older than 2 years",
      last_run_at: "2026-10-26T03:45:00+05:30",
      result: "succeeded",
      facts: { deleted: 0 },
    },
    { key: "load", when: "Always", what: "Past-months collection, in the calls left over", last_run_at: null, result: null, facts: {} },
  ],
  daily_cycle: [
    {
      date: "2026-10-25",
      label: "yesterday",
      causelist_day: { status: "skipped", attempts: 1, finished_at: null, last_error: null },
      lists_stored: 0,
      entries_parsed: 0,
      lists_parse_failed: 0,
      lists_corrected: 0,
      recheck: null,
    },
    {
      date: "2026-10-26",
      label: "today",
      causelist_day: { status: "done", attempts: 1, finished_at: null, last_error: null },
      lists_stored: 4,
      entries_parsed: 900,
      lists_parse_failed: 0,
      lists_corrected: 1,
      recheck: { status: "done", attempts: 1, finished_at: null, last_error: null },
    },
  ],
};

const DISCOVERY = {
  settings: { share: 100, from_year: 2025 },
  window: { status: "current", started_at: null, next_reset_at: null, discovery_calls: 0, share_left: 100 },
  queue: {
    by_kind: {
      party_search: { pending: 0, waiting: 0, running: 0, failed: 0 },
      dossier: { pending: 0, waiting: 0, running: 0, failed: 0 },
      order_pdf: { pending: 0, waiting: 0, running: 0, failed: 0 },
    },
  },
  terms: { active: 0, inactive: 0 },
  cases: { found: 0, created_by_discovery: 0, recommended_from_discovery: 0 },
  last_searched_at: null,
  latest_failures: [],
};

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

function overviewRoutes(functions: Permission[], extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(functions, "central_operator"),
    "GET /admin/data-load/overview": OVERVIEW,
    "GET /admin/data-load/pulse": PULSE,
    "GET /admin/data-load/coverage": COVERAGE,
    ...extra,
  });
}

function automaticRoutes(functions: Permission[], extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(functions, "central_operator"),
    "GET /admin/data-load": progress(),
    "GET /admin/data-load/pulse": PULSE,
    "GET /admin/data-load/schedule": SCHEDULE,
    "GET /admin/discovery": DISCOVERY,
    ...extra,
  });
}

beforeEach(() => resetNav("/data/overview"));

// ------------------------------------------------------------------------------------------------ Overview

describe("Overview (data-collection-redesign, decisions 14-21)", () => {
  it("shows the status line and the four tiles with honest bars", async () => {
    overviewRoutes(READER);
    renderWithClient(<Overview />);
    const status = await screen.findByRole("list", { name: "Collection Status" });
    expect(within(status).getByText("Off")).toBeInTheDocument();
    expect(within(status).getByText("Running")).toBeInTheDocument();
    expect(within(status).getByText("Past months from 1 Jan 2025 to 29 Sep 2026")).toBeInTheDocument();
    const tiles = screen.getByRole("region", { name: "What Is Held" });
    const lists = within(tiles).getByRole("article", { name: "Cause Lists" });
    expect(within(lists).getByText("306 of 664 days")).toBeInTheDocument();
    expect(within(lists).getByText("Working on January 2026")).toBeInTheDocument();
    const bar = within(lists).getByRole("progressbar", { name: "Cause Lists" });
    expect(bar).toHaveAttribute("aria-valuenow", "306");
    expect(bar).toHaveAttribute("aria-valuemax", "664");
    expect(bar).toHaveAttribute("aria-valuetext", "306 of 664 days collected, 267 waiting, 3 failed");
    const orders = within(tiles).getByRole("article", { name: "Order PDFs" });
    expect(await within(orders).findByText(`${f(137932)} of ${f(320869)} stored`)).toBeInTheDocument();
    expect(within(orders).getByText(`${f(182929)} waiting · 8 not available at the court`)).toBeInTheDocument();
    expect(within(orders).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "137932");
    expect(within(orders).getByRole("list", { name: "Legend" })).toHaveTextContent("Not Available");
    const cases = within(tiles).getByRole("article", { name: "Cases" });
    expect(await within(cases).findByText(`${f(59033)} found`)).toBeInTheDocument();
    expect(within(cases).getByText(`${f(58924)} with case details · 109 without`)).toBeInTheDocument();
    const left = within(tiles).getByRole("article", { name: "Still to Fetch" });
    expect(await within(left).findByText(f(183231))).toBeInTheDocument();
    expect(within(left).getByText(`267 cause-list days · 33 case details · ${f(182929)} order PDFs`)).toBeInTheDocument();
    // every tile says what it measures
    expect(within(lists).getByRole("img", { name: /Calendar days from the start/ })).toBeInTheDocument();
  });

  it("opens the Waiting Work table by lane in plain words", async () => {
    overviewRoutes(READER);
    renderWithClient(<Overview />);
    await userEvent.click(await screen.findByRole("button", { name: "Waiting Work" }));
    const table = screen.getByRole("table", { name: "Waiting Work" });
    expectDataTable(table);
    for (const name of ["Past Months", "Daily Updates", "Department Names", "Asked by People", "Fetching", "Failed"]) {
      expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(within(table).getByText(f(167388))).toBeInTheDocument();
  });

  it("the Problems line links each part, and says No Problems when every count is 0", async () => {
    overviewRoutes(READER);
    const { unmount } = renderWithClient(<Overview />);
    const line = await screen.findByLabelText("Problems");
    expect(within(line).getByRole("link", { name: "12 failed fetches" })).toHaveAttribute("href", "/data/queue?status=failed");
    expect(within(line).getByRole("link", { name: "3 possible duplicates" })).toHaveAttribute("href", "/data/duplicates");
    expect(within(line).getByText("109 cases without details")).toBeInTheDocument();
    expect(within(line).getByText("8 orders not available")).toBeInTheDocument();
    unmount();
    const none = { failed: 0, duplicates_review: 0, cases_without_details: 0, orders_not_available: 0, orders_failed: 0 };
    overviewRoutes(READER, { "GET /admin/data-load/overview": { ...OVERVIEW, problems: none } });
    renderWithClient(<Overview />);
    expect(await within(await screen.findByLabelText("Problems")).findByText("No Problems")).toBeInTheDocument();
  });

  it("Right Now shows what is fetching, the calls of the hour and the requests in progress", async () => {
    overviewRoutes(["admin.data_load"]);
    renderWithClient(<Overview />);
    const card = await screen.findByRole("region", { name: "Right Now" });
    expect(await within(card).findByText("Order PDFs · 1")).toBeInTheDocument();
    expect(within(card).getByRole("progressbar", { name: "Calls This Hour" })).toHaveAttribute(
      "aria-valuetext",
      `640 of ${f(1000)} calls made this hour`,
    );
    expect(within(card).getByText("Next reset in 12 min")).toBeInTheDocument();
    expect(within(card).getByText("2")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open Collect Now" })).toHaveAttribute("href", "/data/collect");
  });

  it("polls the pulse every 5 s, the overview every 30 s and the months every 120 s, never in a hidden tab", async () => {
    expect(POLL).toEqual({ pulse: 5_000, overview: 30_000, months: 120_000 });
    overviewRoutes(READER);
    const { client } = renderWithClient(<Overview />);
    await screen.findByText("306 of 664 days");
    for (const [key, ms] of [
      [DC_KEYS.pulse, 5_000],
      [DC_KEYS.overview, 30_000],
      [DC_KEYS.months, 120_000],
    ] as const) {
      const query = client.getQueryCache().find({ queryKey: key })!;
      const options = query.options as { refetchInterval?: number; refetchIntervalInBackground?: boolean };
      expect(options.refetchInterval).toBe(ms);
      expect(options.refetchIntervalInBackground).toBe(false);
    }
  });

  it("shows when the figures were updated and the dated report link with reports.state; no primary", async () => {
    overviewRoutes(READER);
    const { container } = renderWithClient(<Overview />);
    await screen.findByText("306 of 664 days");
    expect(container.querySelector("[data-ui='tab-toolbar']")).toHaveTextContent("Updated just now");
    expect(screen.getByRole("link", { name: "Open the Dated Report" })).toHaveAttribute("href", "/reports/data-health");
    expect(primaryActions(container)).toEqual([]);
  });

  it("words the estimate in two dates with no JSON", async () => {
    overviewRoutes(READER);
    renderWithClient(<Overview />);
    const card = await screen.findByRole("region", { name: "When Will It Finish" });
    expect(within(card).getByText("Cause lists and case details: about Wednesday, 28 October 2026")).toBeInTheDocument();
    expect(within(card).getByText("Every order PDF as well: about Sunday, 8 November 2026")).toBeInTheDocument();
    expect(within(card).getByText(new RegExp(`about 820 court calls an hour of the ${f(1000)} the court allows`))).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "How This Is Worked Out" }));
    expect(within(card).getByText(/3\.1 per cause-list day/)).toBeInTheDocument();
    expect(card.textContent).not.toMatch(/[{}]/);
  });

  it("says why there is no date", async () => {
    const paused = {
      ...OVERVIEW,
      estimate: {
        ...OVERVIEW.estimate,
        details: { finish_at: null, hours: null, calls_needed: null, reason: "paused" },
        all: { finish_at: null, hours: null, calls_needed: null, reason: "connection_off" },
      },
    };
    overviewRoutes(READER, { "GET /admin/data-load/overview": paused });
    renderWithClient(<Overview />);
    expect(await screen.findByText("Cause lists and case details: no date, the automatic collection is paused")).toBeInTheDocument();
    expect(screen.getByText("Every order PDF as well: no date, the court connection is off")).toBeInTheDocument();
  });

  it("Month by Month: in its own box, Not Reached Yet muted, an earlier-orders row, Days for health readers", async () => {
    overviewRoutes(READER);
    renderWithClient(<Overview />);
    const box = await screen.findByRole("region", { name: "Month by Month" });
    const scroll = await within(box).findByRole("region", { name: "Month by Month" });
    expect(scroll).toHaveAttribute("tabindex", "0");
    const table = await within(scroll).findByRole("table", { name: "Month by Month" });
    expectDataTable(table);
    expect(within(table).getByText("January 2025")).toBeInTheDocument();
    expect(within(table).getByText("Done")).toBeInTheDocument();
    const notReached = within(table).getByText("Not Reached Yet").closest("tr")!;
    expect(notReached.className).toMatch(/muted/);
    expect(within(notReached).getByText("40 order PDFs · 31 days")).toBeInTheDocument();
    expect(within(table).getByText("Orders Dated Before January 2025")).toBeInTheDocument();
    expect(within(table).getAllByText(`${f(2978)} of ${f(9876)} stored · ${f(6898)} waiting`).length).toBeGreaterThan(0);
    expect(screen.getByText(/counted by hearing date and orders by order date/)).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Days of January 2025" })).toBeInTheDocument();
  });

  it("no heading is doubled: the panel headings carry the names, the table captions stay hidden", async () => {
    overviewRoutes(READER);
    const { container } = renderWithClient(<Overview />);
    await screen.findByRole("table", { name: "Month by Month" });
    const captions = [...container.querySelectorAll("caption")];
    expect(captions.length).toBeGreaterThan(0);
    for (const caption of captions) expect(caption.className).toMatch(/srCaption/);
  });
});

// ------------------------------------------------------------------------------------------------ Automatic Collection

describe("Automatic Collection (data-collection-redesign, decisions 34-41)", () => {
  beforeEach(() => resetNav("/data/automatic"));

  it("Start a Load is the one primary, for admin.data_load; a reader sees the facts read only", async () => {
    automaticRoutes(READER);
    const first = renderWithClient(<AutomaticCollection />);
    expect(await screen.findByRole("heading", { name: /Load Control/ })).toBeInTheDocument();
    expect(screen.getByText(/You can see the collection/)).toBeInTheDocument();
    expect(primaryActions(first.container)).toEqual([]);
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    first.unmount();
    automaticRoutes(MANAGER);
    const { container } = renderWithClient(<AutomaticCollection />);
    expect(await screen.findByRole("button", { name: "Start a Load" })).toBeInTheDocument();
    expect(primaryActions(container)).toEqual(["Start a Load"]);
    expect(screen.getByText(`Waiting: 101 cause-list days · ${f(5000)} case details · ${f(14900)} order PDFs`, { exact: false })).toBeInTheDocument();
  });

  it("the Start dialog offers Start Load only when something would be fetched", async () => {
    const preview = (notQueued: number, held: number) => ({
      days: 5,
      held_with_lists: held,
      held_no_list: 0,
      waiting: 5 - notQueued - held,
      failed: 0,
      not_queued: notQueued,
      calls_estimate: 1000,
      masters_stale: false,
    });
    let answer = preview(0, 0);
    const api = automaticRoutes(MANAGER, {
      "POST /admin/data-load/preview": () => answer,
      "POST /admin/data-load/start": { days: 5, queued: 2, held_skipped: 0, held_requeued: 0, revived: 0, masters_queued: false },
    });
    renderWithClient(<AutomaticCollection />);
    await userEvent.click(await screen.findByRole("button", { name: "Start a Load" }));
    const dialog = screen.getByRole("dialog", { name: "Start a Load" });
    await userEvent.type(within(dialog).getByLabelText("From"), "2025-02-01");
    await userEvent.type(within(dialog).getByLabelText("To"), "2025-02-05");
    await userEvent.click(within(dialog).getByRole("button", { name: "Check These Dates" }));
    expect(await within(dialog).findByText(/Nothing new to fetch/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Start Load" })).toBeNull();
    expect(within(dialog).getAllByRole("button", { name: "Close" }).length).toBeGreaterThan(0);
    answer = preview(2, 1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Check These Dates" }));
    expect(await within(dialog).findByText(`About ${f(1000)} court calls, about 2 hours at the current pace.`)).toBeInTheDocument();
    expect(within(dialog).getByRole("group", { name: "Days Already Held" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByLabelText("Fetch Them Again"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start Load" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "/admin/data-load/start")).toBe(true));
    expect(api.calls.find((c) => c.path === "/admin/data-load/start")?.body).toEqual({
      from: "2025-02-01",
      to: "2025-02-05",
      held: "refetch",
    });
  });

  it("Pause asks for a reason of 3 to 500 characters with a danger button", async () => {
    const api = automaticRoutes(MANAGER, { "POST /admin/data-load/pause": progress().settings });
    renderWithClient(<AutomaticCollection />);
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog", { name: "Pause the Past-Months Collection" });
    const confirm = within(dialog).getByRole("button", { name: "Pause Collection" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Why Pause It/), "ok");
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Why Pause It/), " now");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(api.calls.find((c) => c.path === "/admin/data-load/pause")?.body).toEqual({ reason: "ok now" }));
  });

  it("What Goes First groups the dates to bring forward in a fieldset and says the current choice", async () => {
    const api = automaticRoutes(MANAGER, {
      "PUT /admin/data-load/order": { settings: progress().settings, reprioritised: 29 },
    });
    renderWithClient(<AutomaticCollection />);
    const form = await screen.findByRole("form", { name: "What Goes First" });
    const fieldset = within(form).getByRole("group", { name: "Bring These Dates Forward" });
    expect(within(fieldset).getByLabelText("From")).toBeInTheDocument();
    expect(within(fieldset).getByLabelText("To")).toBeInTheDocument();
    expect(screen.getByText("Now: Case Details First.")).toBeInTheDocument();
    await userEvent.type(within(form).getByLabelText(/^Reason/), "verification");
    await userEvent.click(within(form).getByRole("button", { name: "Save Priority" }));
    expect(await screen.findByText("Priority saved; 29 waiting items reordered.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/admin/data-load/order")?.body).toEqual({
      load_order: "cases_first",
      first_from: null,
      first_to: null,
      reason: "verification",
    });
  });

  it("Calls by Person shows only when the API sends it", async () => {
    automaticRoutes(READER);
    const first = renderWithClient(<AutomaticCollection />);
    expect(await screen.findByRole("heading", { name: "Court Allowance" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Calls by Person" })).toBeNull();
    first.unmount();
    automaticRoutes(OPERATOR, {
      "GET /admin/napix/health": { by_user: { window: [{ user_id: "u-1", name: "Rina Das", calls: 4, failed: 0 }], today: [] } },
    });
    renderWithClient(<AutomaticCollection />);
    const table = await screen.findByRole("table", { name: "Calls by Person" });
    expect(within(table).getByText("Rina Das")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "By Kind of Work" })).toHaveTextContent("Past Months");
    expect(screen.getByText(/stops when fewer than 150 calls are left in the hour, keeps 100 for daily updates and 50/)).toBeInTheDocument();
  });

  it("the schedule and the daily updates in plain words", async () => {
    automaticRoutes(READER);
    renderWithClient(<AutomaticCollection />);
    const schedule = await screen.findByRole("table", { name: "Daily Schedule" });
    expect(
      within(schedule).getByText(`Refresh cases disposed in the last year, monthly (${f(1234)} in their first year, 56 due now)`),
    ).toBeInTheDocument();
    expect(within(schedule).getByText("Remove court call records older than 2 years (last run removed 0)")).toBeInTheDocument();
    expect(within(schedule).getAllByText("Not Recorded")).toHaveLength(2);
    const daily = screen.getByRole("table", { name: "Daily Updates, Last 7 Days" });
    expect(within(daily).getByText("No List Published")).toBeInTheDocument();
    expect(within(daily).getByText("Checked")).toBeInTheDocument();
  });

  it("Search by Department Names shows its empty state while no name is registered", async () => {
    automaticRoutes(MANAGER);
    renderWithClient(<AutomaticCollection />);
    expect(await screen.findByText(/No department names are registered yet/)).toBeInTheDocument();
    expect(document.getElementById("department-names")).not.toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ Collect Now

describe("Collect Now (round 1: today's forms moved unchanged)", () => {
  beforeEach(() => resetNav("/data/collect"));

  const held = {
    case: {
      id: "c-1",
      ref_no: "ASLMS/GHC/CASE/2026/000001",
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

  it("shows each card by its own function, and no primary", async () => {
    browserApi({ "GET /me": makeMe(["admin.napix_refetch"], "central_operator") });
    const first = renderWithClient(<CollectNow />);
    expect(await screen.findByRole("heading", { name: "One Day's Cause Lists" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fetch Again" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "One Case" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Court Reference Lists" })).toBeNull();
    expect(primaryActions(first.container)).toEqual([]);
    first.unmount();
    browserApi({ "GET /me": makeMe(["admin.masters_sync"], "central_operator"), "GET /admin/data-health": { masters: [] } });
    const second = renderWithClient(<CollectNow />);
    expect(await screen.findByRole("heading", { name: "Court Reference Lists" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update Now" })).toBeInTheDocument();
    second.unmount();
    browserApi({ "GET /me": makeMe(["admin.data_load"], "super_admin") });
    renderWithClient(<CollectNow />);
    expect(await screen.findByRole("heading", { name: "One Case" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Fetch Again" })).toBeNull();
  });

  it("One Case: already held, Fetch Anyway resends with force; Cancel sends nothing", async () => {
    const api = browserApi({
      "GET /me": makeMe(MANAGER, "super_admin"),
      "POST /admin/data-load/fetch": (call: { body: unknown }) =>
        (call.body as { force: boolean }).force
          ? { source: "court", calls: 1, created: 0, items: [held], unmatched: [] }
          : json(409, { detail: { code: "already_held", message: "held", cases: [held] } }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "One Case" });
    await userEvent.type(within(form).getByLabelText("CNR"), "gahc010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const dialog = await screen.findByRole("dialog", { name: "Already in the Database" });
    expect(within(dialog).getByText(/ASLMS\/GHC\/CASE\/2026\/000001: details fetched 8 Oct 2026/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.calls.filter((c) => c.path === "/admin/data-load/fetch")).toHaveLength(1);
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const again = await screen.findByRole("dialog", { name: "Already in the Database" });
    await userEvent.click(within(again).getByRole("button", { name: "Fetch Anyway" }));
    expect(await screen.findByText(/not visible to you/)).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/admin/data-load/fetch").map((c) => c.body)).toEqual([
      { kind: "cnr", cnr: "GAHC010129772026", force: false },
      { kind: "cnr", cnr: "GAHC010129772026", force: false },
      { kind: "cnr", cnr: "GAHC010129772026", force: true },
    ]);
  });

  it("One Case: the results can be queued for details", async () => {
    const found = { ...held, visible: true, dossier_status: "none" };
    const api = browserApi({
      "GET /me": makeMe(MANAGER, "super_admin"),
      "POST /admin/data-load/fetch": { source: "court", calls: 1, created: 1, items: [found], unmatched: [] },
      "POST /admin/data-load/fetch-details": {
        items: [{ ref: "ASLMS/GHC/CASE/2026/000001", case: found, state: "queued", queue: null }],
      },
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "One Case" });
    await userEvent.type(within(form).getByLabelText("CNR"), "GAHC010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "ASLMS/GHC/CASE/2026/000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Fetch Details" }));
    expect(await screen.findByText("1 cases queued for details.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/admin/data-load/fetch-details")?.body).toEqual({
      cases: ["ASLMS/GHC/CASE/2026/000001"],
      force: false,
    });
  });

  it("One Case: no result says so in words, and results sit in a scroll box", async () => {
    browserApi({
      "GET /me": makeMe(MANAGER, "super_admin"),
      "POST /admin/data-load/fetch": { source: "court", calls: 1, created: 0, items: [], unmatched: [] },
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "One Case" });
    await userEvent.type(within(form).getByLabelText("CNR"), "GAHC010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    expect(await screen.findByText("The court found no case for this search.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing to show.")).toBeNull();
  });

  it("One Case: the results table is inside a labelled scroll box", async () => {
    browserApi({
      "GET /me": makeMe(MANAGER, "super_admin"),
      "POST /admin/data-load/fetch": {
        source: "court",
        calls: 1,
        created: 1,
        items: [{ ...held, visible: true, dossier_status: "none" }],
        unmatched: [],
      },
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "One Case" });
    await userEvent.type(within(form).getByLabelText("CNR"), "GAHC010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    const box = await screen.findByRole("region", { name: "Results" });
    expect(within(box).getByRole("table", { name: "Results" })).toBeInTheDocument();
  });

  it("One Day's Cause Lists warns before re-fetching a day already held and resends with force", async () => {
    const api = browserApi({
      "GET /me": makeMe(["admin.napix_refetch"], "central_operator"),
      "POST /admin/napix/refetch/day": (call: { body: unknown }) =>
        (call.body as { force?: boolean }).force
          ? QUEUED_DAY
          : json(409, { detail: { code: "already_held", message: "held", status: "done", lists_stored: 2, finished_at: null } }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "Re-fetch a Day" });
    await userEvent.type(within(form).getByLabelText("Date"), "2025-01-06");
    await userEvent.click(within(form).getByRole("button", { name: "Re-fetch a Day" }));
    const dialog = await screen.findByRole("dialog", { name: "Already in the Database" });
    expect(within(dialog).getByText("That day is already held (done, 2 lists stored).")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Fetch Anyway" }));
    expect(await screen.findByText("Cause-list Days queued (pending).")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/admin/napix/refetch/day").map((c) => c.body)).toEqual([
      { date: "2025-01-06" },
      { date: "2025-01-06", force: true },
    ]);
  });

  it("Court Reference Lists: each list's last update and rows", async () => {
    browserApi({
      "GET /me": makeMe(["admin.masters_sync"], "central_operator"),
      "GET /admin/data-health": { masters: [{ master: "case_type", fetched_at: "2026-10-26T06:00:00+05:30", row_count: 120 }] },
    });
    renderWithClient(<CollectNow />);
    const table = await screen.findByRole("table", { name: "Court Reference Lists" });
    expect(within(table).getByText("Case Types")).toBeInTheDocument();
    expect(within(table).getByText("120 rows")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------ the frame

describe("the Data Collection frame", () => {
  it("/data opens Overview, the first tab", async () => {
    resetNav("/data");
    browserApi({ "GET /me": makeMe(READER, "state_oversight") });
    renderWithClient(<DataIndex />);
    await waitFor(() => expect(navState.replace).toHaveBeenCalledWith("/data/overview"));
  });

  it("the frame is a stack, so the page keeps its gutter", async () => {
    resetNav("/data/overview");
    browserApi({ "GET /me": makeMe(READER, "state_oversight") });
    const { container } = renderWithClient(
      <DataFrame>
        <p>body</p>
      </DataFrame>,
    );
    await screen.findByText("body");
    expect((container.firstElementChild as HTMLElement).className).toBe("stack");
  });
});

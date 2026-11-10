/**
 * Collect Now carried out at once (design data-collection-redesign, decisions 22-33; round 3): the progress panel, the
 * list and day checks that write nothing, the "use everything" panel and its confirm, one bulk request at a time, the
 * Requests card with its bars, Stop's confirm and the items panel, and the refresh intervals.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { CollectProgress } from "@/components/ui";
import type { Permission } from "@/lib/api/types";
import { DC_KEYS, REQUEST_POLL, requestCounts, requestWhat } from "@/lib/dataCollection";
import { formatNumber as f } from "@/lib/format";
import { PLAN, detail, requestsList, summary } from "@/test/collectFixtures";
import { resetNav } from "@/test/nav";
import { browserApi, json, makeMe, primaryActions, renderWithClient } from "@/test/render";

import { CollectNow } from "./CollectNow";
import { nb } from "@/test/dates";

const MANAGER: Permission[] = ["admin.data_load"];
const OPERATOR: Permission[] = ["admin.napix_refetch", "admin.masters_sync", "reports.state"];

function line(over: Record<string, unknown>) {
  return { case: null, cnr: null, details_fetched_at: null, merged_into_ref_no: null, matches: 0, ...over };
}

const LIST_CHECK = {
  items: [
    line({
      line: "GAHC010000112025",
      state: "will_fetch",
      case: { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000011", cnr: "GAHC010000112025", case_no_text: "WP(C)/11/2025" },
      cnr: "GAHC010000112025",
    }),
    line({ line: "GAHC019999992025", state: "will_fetch", cnr: "GAHC019999992025" }),
    line({ line: "WP(C) 999/2025", state: "not_held" }),
    line({ line: "hello world", state: "not_a_reference" }),
    line({ line: "ASLMS/GHC/CASE/2026/000016", state: "merged", merged_into_ref_no: "ASLMS/GHC/CASE/2026/000017" }),
  ],
  counts: { will_fetch: 2, already_has_details: 0, not_held: 1, several_match: 0, not_a_reference: 1, merged: 1, no_reference: 0 },
  force: false,
  to_fetch: 2,
  plan: PLAN,
  bulk: null,
};

const DAY_CHECK = {
  date: "2026-10-23",
  scope: "never",
  lists: 14,
  cases_listed: 1191,
  with_details: 1100,
  details_from: "2026-10-01T10:00:00+05:30",
  details_to: "2026-10-28T10:00:00+05:30",
  never_fetched: 91,
  refreshed_recently: 30,
  no_reference: 2,
  to_fetch: 89,
  plan: PLAN,
  bulk: null,
};

const BULK_OUT = {
  request_id: "r-2",
  kind: "list",
  to_fetch: 2,
  queued: 2,
  already_waiting: 0,
  left_out: [],
  priority: 5,
  expected_end: "2026-10-29T17:20:00+05:30",
};

function routes(functions: Permission[], extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": makeMe(functions, "super_admin"),
    "GET /admin/data-load/requests": requestsList(),
    "GET /admin/data-health": { masters: [] },
    ...extra,
  });
}

describe("the progress panel (decision 25)", () => {
  it("shows the case details step, then the order PDFs as a segmented bar with the time left", () => {
    const none = { total: 0, stored: 0, not_available: 0, failed: 0, waiting: 0 };
    const { rerender } = renderWithClient(<CollectProgress details="fetching" orders={none} />);
    const panel = screen.getByRole("region", { name: "Collection Progress" });
    expect(within(panel).getByText("Fetching")).toBeInTheDocument();
    expect(within(panel).getByText("The order PDFs are counted once the case details are in.")).toBeInTheDocument();
    rerender(
      <CollectProgress details="done" orders={{ total: 40, stored: 12, not_available: 1, failed: 0, waiting: 27 }} etaSeconds={130} />,
    );
    const bar = screen.getByRole("progressbar", { name: "Order PDFs" });
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "40");
    expect(bar).toHaveAttribute("aria-valuetext", "12 of 40 stored · 1 not available at the court");
    expect(screen.getByText("About 2 min left at the current pace.")).toBeInTheDocument();
    rerender(<CollectProgress details={null} orders={none} />);
    expect(screen.queryByText("Case Details")).toBeNull();
    expect(screen.getByText("No order is known for this case yet.")).toBeInTheDocument();
  });
});

describe("Collect Now's cards (decisions 22, 26-29)", () => {
  beforeEach(() => resetNav("/data/collect"));

  it("shows the cards in order by function, and no primary", async () => {
    routes(MANAGER);
    const { container } = renderWithClient(<CollectNow />);
    await screen.findByRole("heading", { name: "One Case" });
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual(["One Case", "Several Cases", "All Cases Listed on a Day"]);
    expect(primaryActions(container)).toEqual([]);
  });

  it("Several Cases: the check writes nothing and words every line; Collect Everything confirms with the panel", async () => {
    const api = routes(MANAGER, {
      "POST /admin/data-load/collect/list/check": LIST_CHECK,
      "POST /admin/data-load/collect": BULK_OUT,
      "GET /admin/data-load/requests/r-2": detail({ request_id: "r-2", kind: "list", bulk: true, using_everything: true, cases: 2 }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "Several Cases" });
    await userEvent.type(within(form).getByLabelText(/Cases, One Per Line/), "GAHC010000112025{enter}GAHC019999992025{enter}{enter}");
    await userEvent.click(within(form).getByLabelText("Also Fetch Cases That Already Have Details"));
    await userEvent.click(within(form).getByRole("button", { name: "Check List" }));
    const table = await screen.findByRole("table", { name: "Several Cases" });
    expect(within(table).getByText("New From the Court")).toBeInTheDocument();
    expect(within(table).getByText("Not Held")).toBeInTheDocument();
    expect(within(table).getByText("Use One Case to search the court for it.")).toBeInTheDocument();
    expect(within(table).getByText("Not a Case Reference")).toBeInTheDocument();
    expect(within(table).getByText("Merged Into ASLMS/GHC/CASE/2026/000017")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/admin/data-load/collect/list/check")?.body).toEqual({
      lines: ["GAHC010000112025", "GAHC019999992025"],
      force: true,
    });
    expect(api.calls.some((c) => c.path === "/admin/data-load/collect")).toBe(false);
    // the "use everything" panel says what others experience and the estimate
    const panel = screen.getByRole("note", { name: "This Request Uses the Whole Allowance" });
    expect(within(panel).getByText(/fewer than 50 calls are left in the hour/)).toBeInTheDocument();
    expect(within(panel).getByText("Nothing already collected is affected.")).toBeInTheDocument();
    expect(within(panel).getByText(new RegExp(`About ${f(1250)} court calls: about 640 in this hour`))).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Collect Everything" }));
    const dialog = await screen.findByRole("dialog", { name: "Collect Everything" });
    expect(within(dialog).getByRole("note", { name: "This Request Uses the Whole Allowance" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Collect Everything" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.path === "/admin/data-load/collect")?.body).toEqual({
        kind: "list",
        lines: ["GAHC010000112025", "GAHC019999992025"],
        force: true,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Collecting" })).toBeInTheDocument();
  });

  it("a second bulk request says who is using the allowance, what and since when", async () => {
    routes(MANAGER, {
      "POST /admin/data-load/collect/list/check": LIST_CHECK,
      "POST /admin/data-load/collect": json(409, {
        detail: {
          code: "bulk_running",
          message: "one at a time",
          request_id: "r-1",
          asked_by: "Super Administrator",
          kind: "day",
          date: "2026-10-23",
          cases: 89,
          asked_at: "2026-10-29T15:50:00+05:30",
        },
      }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "Several Cases" });
    await userEvent.type(within(form).getByLabelText(/Cases, One Per Line/), "GAHC010000112025");
    await userEvent.click(within(form).getByRole("button", { name: "Check List" }));
    await userEvent.click(await screen.findByRole("button", { name: "Collect Everything" }));
    const dialog = await screen.findByRole("dialog", { name: "Collect Everything" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Collect Everything" }));
    expect(
      await screen.findByText(/A request by Super Administrator \(Cases Listed on 23 Oct 2026\) is using the whole allowance since/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a check while a bulk request runs names it and offers no Collect Everything", async () => {
    routes(MANAGER, {
      "POST /admin/data-load/collect/list/check": {
        ...LIST_CHECK,
        bulk: summary({ kind: "list", bulk: true, using_everything: true, cases: 12 }),
      },
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "Several Cases" });
    await userEvent.type(within(form).getByLabelText(/Cases, One Per Line/), "GAHC010000112025");
    await userEvent.click(within(form).getByRole("button", { name: "Check List" }));
    expect(await screen.findByText(/A request by Super Administrator \(List of 12 Cases\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collect Everything" })).toBeDisabled();
  });

  it("All Cases Listed on a Day: the check's figures, and nothing to fetch says so with no button", async () => {
    let toFetch = 89;
    const api = routes(MANAGER, {
      "GET /admin/data-load/collect/day": () => ({ ...DAY_CHECK, to_fetch: toFetch }),
      "POST /admin/data-load/collect": { ...BULK_OUT, kind: "day" },
      "GET /admin/data-load/requests/r-2": detail({ request_id: "r-2", kind: "day", bulk: true, date: "2026-10-23" }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "All Cases Listed on a Day" });
    await userEvent.type(within(form).getByLabelText("Date"), "2026-10-23");
    await userEvent.click(within(form).getByLabelText(/Every Case Listed/));
    expect(within(form).getByText(/refreshed in the last 6 hours are left out/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Check This Day" }));
    expect(await screen.findByText("Lists on That Day")).toBeInTheDocument();
    expect(screen.getByText(f(1191))).toBeInTheDocument();
    expect(screen.getByText("Refreshed in the Last 6 Hours")).toBeInTheDocument();
    expect(screen.getByText(/last refreshed between 1 Oct 2026 and 28 Oct 2026/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.startsWith("/admin/data-load/collect/day"))?.path).toBe(
      "/admin/data-load/collect/day?date=2026-10-23&scope=all",
    );
    await userEvent.click(screen.getByRole("button", { name: "Collect Everything" }));
    const dialog = await screen.findByRole("dialog", { name: "Collect Everything" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Collect Everything" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.path === "/admin/data-load/collect")?.body).toEqual({
        kind: "day",
        date: "2026-10-23",
        scope: "all",
      }),
    );
    toFetch = 0;
    await userEvent.click(within(form).getByRole("button", { name: "Check This Day" }));
    expect(await screen.findByText("Every case listed on this day already has details.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Collect Everything" })).toBeNull();
  });

  it("the day check's refusals are worded", async () => {
    routes(MANAGER, {
      "GET /admin/data-load/collect/day": json(400, { detail: { code: "no_lists", message: "no cause list" } }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "All Cases Listed on a Day" });
    await userEvent.type(within(form).getByLabelText("Date"), "2026-10-20");
    await userEvent.click(within(form).getByRole("button", { name: "Check This Day" }));
    expect(await screen.findByText("No cause list of that day is held. Fetch the day's cause lists first.")).toBeInTheDocument();
  });

  it("One Day's Cause Lists shows the request's progress, keyed by its request id", async () => {
    routes(["admin.napix_refetch"], {
      "POST /admin/napix/refetch/day": {
        kind: "causelist_day",
        ref: "2025-01-06",
        queue_id: "q-1",
        status: "pending",
        priority: 3,
        attempts: 0,
        not_before: null,
        lane: "request",
        napix_enabled: false,
        request_id: "r-3",
      },
      "GET /admin/data-load/requests/r-3": detail({ request_id: "r-3", kind: "refetch_day", ref: "2025-01-06", cases: null, by_kind: {} }),
    });
    renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "Re-fetch a Day" });
    await userEvent.type(within(form).getByLabelText("Date"), "2025-01-06");
    await userEvent.click(within(form).getByRole("button", { name: "Re-fetch a Day" }));
    expect(await screen.findByRole("progressbar", { name: nb("Cause Lists of 6 Jan 2025") })).toHaveAttribute(
      "aria-valuetext",
      "0 of 1 done · 1 waiting",
    );
  });
});

describe("the Requests card (decisions 23, 31-32)", () => {
  beforeEach(() => resetNav("/data/collect"));

  const bulk = summary({
    request_id: "r-2",
    kind: "day",
    bulk: true,
    date: "2026-10-23",
    cases: 89,
    using_everything: true,
    expected_end: "2026-10-29T17:20:00+05:30",
    counts: { waiting: 60, waiting_retry: 2, fetching: 1, done: 20, not_found: 3, failed: 3 },
    total: 89,
  });
  const done = summary({ finished: true, counts: { waiting: 0, waiting_retry: 0, fetching: 0, done: 1, not_found: 0, failed: 0 } });

  it("lists the requests first with their bars and states", async () => {
    routes(MANAGER, { "GET /admin/data-load/requests": requestsList([bulk, done]) });
    renderWithClient(<CollectNow />);
    const card = await screen.findByRole("region", { name: "Requests" });
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings[0]).toHaveTextContent("Requests");
    expect(within(card).getByText("Cases Listed on 23 Oct 2026")).toBeInTheDocument();
    expect(within(card).getByRole("progressbar", { name: nb("Cases Listed on 23 Oct 2026") })).toHaveAttribute(
      "aria-valuetext",
      "23 of 89 done · 1 fetching · 62 waiting · 3 failed",
    );
    expect(within(card).getByText("Using the Whole Allowance")).toBeInTheDocument();
    expect(within(card).getByText("Finished")).toBeInTheDocument();
    expect(within(card).getAllByText("Super Administrator")).toHaveLength(2);
  });

  it("Stop Using Everything confirms first and sends the stop; only with admin.data_load", async () => {
    const api = routes(MANAGER, {
      "GET /admin/data-load/requests": requestsList([bulk]),
      "POST /admin/data-load/requests/r-2/stop": { request_id: "r-2", moved: 61 },
    });
    renderWithClient(<CollectNow />);
    const card = await screen.findByRole("region", { name: "Requests" });
    await userEvent.click(within(card).getByRole("button", { name: "Stop Using Everything" }));
    const dialog = await screen.findByRole("dialog", { name: "Stop Using the Whole Allowance" });
    expect(within(dialog).getByText(/The rest of this request \(61 items\) will be fetched in the normal turn/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("/stop"))).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Using Everything" }));
    expect(await screen.findByText("Stopped: 61 items go back to the normal turn.")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/admin/data-load/requests/r-2/stop")).toHaveLength(1);
  });

  it("an operator sees the requests and the items, without Stop", async () => {
    routes(OPERATOR, {
      "GET /admin/data-load/requests": requestsList([bulk]),
      "GET /admin/data-load/requests/r-2": detail({
        ...bulk,
        items: [
          { kind: "dossier", ref: "GAHC010000112025", state: "fetching", attempts: 1, not_before: null, problem: null, priority: 5 },
          {
            kind: "order_pdf",
            ref: "GAHC010000112025|3|2026-10-01",
            state: "waiting_retry",
            attempts: 2,
            not_before: "2026-10-29T16:40:00+05:30",
            problem: "NapixUnavailable: 502",
            priority: 5,
          },
        ],
      }),
    });
    renderWithClient(<CollectNow />);
    const card = await screen.findByRole("region", { name: "Requests" });
    expect(within(card).queryByRole("button", { name: "Stop Using Everything" })).toBeNull();
    await userEvent.click(within(card).getByRole("button", { name: "Show Items" }));
    const panel = await screen.findByRole("dialog", { name: nb("Items: Cases Listed on 23 Oct 2026") });
    const table = await within(panel).findByRole("table", { name: nb("Items: Cases Listed on 23 Oct 2026") });
    expect(within(table).getByText("Fetching")).toBeInTheDocument();
    expect(within(table).getByText("Waiting to Retry")).toBeInTheDocument();
    expect(within(table).getByText(/Tried again at about/)).toBeInTheDocument();
    expect(within(table).getByText("NapixUnavailable: 502")).toBeInTheDocument();
  });

  it("refreshes the list every 5 s while a request runs, else every 30 s, never in a hidden tab", async () => {
    expect(REQUEST_POLL).toEqual({ watched: 2_000, active: 5_000, idle: 30_000 });
    routes(MANAGER, { "GET /admin/data-load/requests": requestsList([bulk]) });
    const { client } = renderWithClient(<CollectNow />);
    await screen.findByRole("region", { name: "Requests" });
    const query = client.getQueryCache().find({ queryKey: DC_KEYS.requests })!;
    const options = query.options as {
      refetchInterval: (q: unknown) => number | false;
      refetchIntervalInBackground?: boolean;
    };
    expect(options.refetchIntervalInBackground).toBe(false);
    expect(options.refetchInterval(query)).toBe(5_000);
    query.setData(requestsList([]));
    expect(options.refetchInterval(query)).toBe(30_000);
  });

  it("refreshes a watched request every 2 s until it has finished; says when the collector waits or the limit is used up", async () => {
    routes(MANAGER, {
      "POST /admin/data-load/fetch": {
        source: "court",
        calls: 1,
        created: 0,
        items: [
          {
            case: {
              id: "c-1",
              ref_no: "ASLMS/GHC/CASE/2026/000001",
              cnr: "GAHC010129772026",
              case_no_text: "WP(C)/3600/2026",
              is_provisional: false,
              petitioner_summary: null,
              respondent_summary: null,
              status: "pending",
              next_hearing: null,
              last_listed_on: null,
              last_listing: null,
            },
            visible: true,
            owner_office_code: null,
            in_pool: true,
            claimable: false,
            match: "cnr",
            dossier_status: "fetched",
            dossier_fetched_at: null,
          },
        ],
        unmatched: [],
      },
      "POST /admin/data-load/collect": { ...BULK_OUT, request_id: "r-1", kind: "cases", priority: 3 },
      "GET /admin/data-load/requests/r-1": detail({
        collector: { last_active_at: "2026-10-29T14:05:00+05:30", now_waiting: true, not_running: true },
        window: { remaining: 0, next_reset_at: "2026-10-29T16:35:00+05:30", limit_used_up: true, resumes_at: "2026-10-29T16:36:00+05:30" },
      }),
    });
    const { client } = renderWithClient(<CollectNow />);
    const form = await screen.findByRole("form", { name: "One Case" });
    await userEvent.type(within(form).getByLabelText("CNR"), "GAHC010129772026");
    await userEvent.click(within(form).getByRole("button", { name: "Fetch" }));
    expect(await screen.findByText(/Waiting for the collector to start \(last active/)).toBeInTheDocument();
    expect(screen.getByText(/The court's hourly limit is used up; this continues at about/)).toBeInTheDocument();
    const watched = client.getQueryCache().find({ queryKey: [...DC_KEYS.request("r-1"), 0] })!;
    const options = watched.options as { refetchInterval: (q: unknown) => number | false; refetchIntervalInBackground?: boolean };
    expect(options.refetchIntervalInBackground).toBe(false);
    expect(options.refetchInterval(watched)).toBe(2_000);
    watched.setData(detail({ finished: true }));
    expect(options.refetchInterval(watched)).toBe(false);
  });

  it("words what each request asked for and its counts", () => {
    expect(requestWhat(summary({ kind: "list", cases: 12 }))).toBe("List of 12 Cases");
    expect(requestWhat(summary({ kind: "cases", cases: 1 }))).toBe("One Case");
    expect(requestWhat(summary({ kind: "masters", cases: null }))).toBe("Court Reference Lists");
    expect(requestWhat(summary({ kind: "refetch_order", cases: 1 }))).toBe("One Order PDF Again");
    expect(requestCounts({ waiting: 1, done: 2, not_found: 1 }, 4)).toBe("3 of 4 done · 1 waiting");
  });
});

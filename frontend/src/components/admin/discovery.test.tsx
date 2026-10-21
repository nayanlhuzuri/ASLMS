import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Discovery } from "@/components/data/Discovery";
import type { DiscoveryCase, DiscoverySummary, DiscoveryTerm, Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient } from "@/test/render";

import { CourtSearch } from "./mapping/CourtSearch";
import { MappingFrame } from "./mapping/MappingFrame";

function term(extra: Partial<DiscoveryTerm> = {}): DiscoveryTerm {
  return {
    id: "t-1",
    term: "PRITAM SAIKIA",
    active: true,
    departments: ["EDU"],
    rules: [{ kind: "prefix", rule_id: "np-1", office_code: "EDU", is_active: true }],
    years: { done: 2, waiting: 0, failed: 0 },
    last_searched_at: "2026-10-13T10:00:00+05:30",
    cases_found: 2,
    found_last_7_days: 1,
    full_sweep_queued_at: "2026-10-12T10:00:00+05:30",
    recent_sweep_queued_at: null,
    ...extra,
  };
}

function found(n: number, extra: Partial<DiscoveryCase> = {}): DiscoveryCase {
  return {
    case: {
      id: `c-${n}`,
      ref_no: `ASLMS/EDU/CASE/2026/00000${n}`,
      cnr: `GAHC0100000${n}2026`,
      case_no_text: `CONT.CAS(C)/${n}/2026`,
      is_provisional: false,
      petitioner_summary: "RAM KUMAR",
      respondent_summary: "PRITAM SAIKIA AND 2 ORS",
      status: "pending",
      next_hearing_date: null,
      last_listed_on: null,
      last_listing: null,
    },
    reg_year: 2026,
    first_found_at: "2026-10-13T10:00:00+05:30",
    last_found_at: "2026-10-13T10:00:00+05:30",
    owner_office_code: null,
    recommendation: null,
    claimable: true,
    ...extra,
  };
}

function summary(extra: Partial<DiscoverySummary> = {}): DiscoverySummary {
  return {
    settings: { share: 100, from_year: 2025 },
    window: {
      status: "current",
      started_at: "2026-10-14T10:34:00+05:30",
      next_reset_at: "2026-10-14T11:34:00+05:30",
      discovery_calls: 12,
      share_left: 88,
    },
    queue: {
      by_kind: {
        party_search: { pending: 4, waiting: 1, running: 0, failed: 1 },
        dossier: { pending: 3, waiting: 0, running: 1, failed: 0 },
        order_pdf: { pending: 0, waiting: 0, running: 0, failed: 0 },
      },
    },
    terms: { active: 3, inactive: 1 },
    cases: { found: 9, created_by_discovery: 4, recommended_from_discovery: 2 },
    last_searched_at: "2026-10-14T10:40:00+05:30",
    latest_failures: [
      { kind: "party_search", ref: "GAHC01|P|2025|PRITAM SAIKIA", last_error: "NapixUnavailable: 503", finished_at: null },
    ],
    ...extra,
  };
}

const ADMIN: Permission[] = ["admin.keywords", "cases.claim", "cases.view_scope"];

beforeEach(() => {
  resetNav("/admin/mapping/discovery");
});

describe("Court search tab", () => {
  it("shows only with admin.keywords", async () => {
    browserApi({ "GET /me": makeMe(["admin.counsel_codes"], "dept_admin") });
    renderWithClient(
      <MappingFrame>
        <p>body</p>
      </MappingFrame>,
    );
    await screen.findByText("body");
    const nav = screen.getByRole("navigation", { name: "Department mapping sections" });
    expect(within(nav).queryByRole("link", { name: "Court search" })).toBeNull();
  });

  it("lists the names and opens a name's cases with Claim through the claim dialog", async () => {
    const own = "/cases/ASLMS-EDU-CASE-2026-000001";
    const api = browserApi({
      "GET /me": makeMe(ADMIN, "dept_admin"),
      "GET /admin/discovery/terms": { items: [term(), term({ id: "t-2", term: "ANIL BORA", active: false })], total: 2 },
      "GET /admin/discovery/terms/t-1/cases": {
        items: [
          found(1),
          found(2, {
            owner_office_code: "HEALTH",
            claimable: false,
            recommendation: { office_code: "EDU", band: "medium", score: 0.8, status: "recommended" },
          }),
        ],
        total: 2,
      },
      [`GET ${own}/ownership`]: {
        primary: null,
        watchers: [],
        recommendations: [],
        open_transfer: null,
        actions: { claim: true, claim_departments: ["EDU"] },
      },
      [`POST ${own}/claim`]: json(201, {}),
    });
    renderWithClient(<CourtSearch />);
    const table = await screen.findByRole("table", { name: "Names searched at the court" });
    expect(within(table).getByText("PRITAM SAIKIA")).toBeInTheDocument();
    expect(within(table).getByText("Not searched now")).toBeInTheDocument();
    expect(screen.queryByText(/calls?\b/i)).toBeNull(); // no call counts for users
    await userEvent.click(screen.getByRole("button", { name: "Show the cases found for PRITAM SAIKIA" }));
    const cases = await screen.findByRole("table", { name: "Cases found for PRITAM SAIKIA" });
    const rows = within(cases).getAllByRole("row");
    expect(within(rows[2]!).getByText("HEALTH")).toBeInTheDocument();
    expect(within(rows[2]!).queryByRole("button", { name: "Claim" })).toBeNull();
    await userEvent.click(within(rows[1]!).getByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    await within(dialog).findByText("EDU");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === `${own}/claim`)?.body).toEqual({ office_code: "EDU" }),
    );
  });

  it("a name and years are queued every time, with no searched-before question", async () => {
    const api = browserApi({
      "GET /me": makeMe(ADMIN, "dept_admin"),
      "GET /admin/discovery/terms": { items: [term()], total: 1 },
      "GET /admin/discovery/terms/t-1/cases": { items: [], total: 0 },
      "POST /admin/discovery/search": json(202, { term_id: "t-1", term: "PRITAM SAIKIA", years: [2011, 2010], queued: true }),
    });
    renderWithClient(<CourtSearch />);
    const form = await screen.findByRole("form", { name: "Search older years" });
    await userEvent.type(within(form).getByLabelText("Name"), "Pritam Saikia");
    await userEvent.type(within(form).getByLabelText("Years"), "1900");
    await userEvent.click(within(form).getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/Enter years from 1950/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.clear(within(form).getByLabelText("Years"));
    await userEvent.type(within(form).getByLabelText("Years"), "2010-2011");
    await userEvent.click(within(form).getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Searching the court. Results will appear here as they are found.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    // the same name and years again: searched again straight away
    await userEvent.type(within(form).getByLabelText("Years"), "2010-2011");
    await userEvent.click(within(form).getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(2));
    expect(screen.queryByRole("dialog")).toBeNull();
    const sent = api.calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(sent).toEqual([
      { name: "PRITAM SAIKIA", years: [2011, 2010] },
      { name: "PRITAM SAIKIA", years: [2011, 2010] },
    ]);
  });
});

describe("Discovery data tab", () => {
  beforeEach(() => resetNav("/data/discovery"));

  it("shows the share and hides the sweep button without admin.data_load", async () => {
    browserApi({ "GET /me": makeMe(["reports.state"], "state_oversight"), "GET /admin/discovery": summary() });
    renderWithClient(<Discovery />);
    expect(await screen.findByText("12 of 100 calls used in this window; 88 left.")).toBeInTheDocument();
    expect(screen.getByText("GAHC01|P|2025|PRITAM SAIKIA")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sweep every name now" })).toBeNull();
  });

  it("the sweep asks first and posts for admin.data_load", async () => {
    const api = browserApi({
      "GET /me": makeMe(["admin.data_load"], "super_admin"),
      "GET /admin/discovery": summary(),
      "POST /admin/discovery/sweep": json(202, { terms: 3, rows_queued: 6 }),
    });
    renderWithClient(<Discovery />);
    await userEvent.click(await screen.findByRole("button", { name: "Sweep every name now" }));
    const dialog = screen.getByRole("dialog", { name: "Queue a discovery sweep" });
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Sweep every name now" }));
    expect(await screen.findByText("6 searches queued for 3 name(s).")).toBeInTheDocument();
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("CourtSearch renders a DataTable with a primary cell", async () => {
    resetNav("/admin/mapping/court-search");
    browserApi({
      "GET /me": makeMe(ADMIN, "dept_admin"),
      "GET /admin/discovery/terms": { items: [term()], total: 1 },
      "GET /admin/discovery/terms/t-1/cases": { items: [found(1)], total: 1 },
    });
    renderWithClient(<CourtSearch />);
    expectDataTable(await screen.findByRole("table", { name: "Names searched at the court" }));
    await userEvent.click(screen.getByRole("button", { name: "Show the cases found for PRITAM SAIKIA" }));
    expectDataTable(await screen.findByRole("table", { name: "Cases found for PRITAM SAIKIA" }));
  });
});

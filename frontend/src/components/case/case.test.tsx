import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseDetail, CaseOwnershipView, DocumentItem, Note, OwnershipActions, Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { CaseFrame } from "./CaseFrame";
import { Details } from "./Details";
import { Documents } from "./Documents";
import { Links } from "./Links";
import { Notes } from "./Notes";
import { Orders } from "./Orders";
import { Overview } from "./Overview";

const REF = "ASLMS-GOA-CASE-2026-000001";
const BASE = `/cases/${REF}`;
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download"];

function detail(extra: Partial<CaseDetail> = {}): CaseDetail {
  return {
    id: "c-1",
    ref_no: "ASLMS/GOA/CASE/2026/000001",
    access_basis: ["owner"],
    acts: [{ act_name_as_listed: "Constitution of India", national_act_code: "C001", section: "226" }],
    advocates: [
      { name_as_listed: "A. Das", side: "petitioner", counsel_code: null, bar_reg_no: null, is_current: true },
      { name_as_listed: "SC, EDU", side: "respondent", counsel_code: "SC,EDU", bar_reg_no: null, is_current: true },
    ],
    applications: [{ ia_number: "IA(C)/1/2026", filing_date: "2026-02-01", party_name: "RAM", status: "pending" }],
    bench: { bench_id: 2048, bench_name: "Single Bench", judge_names: "Hon'ble Justice X" },
    claimable: false,
    classification: {
      bench_id: null,
      bench_name: "Single Bench",
      bench_type_code: 1,
      category: "Service",
      category_code: 12,
      coram: "Justice X",
      coram_designation: "Judge",
      judicial_branch: "Civil",
      napix_bench_id: 2048,
      sub_category: "Transfer",
    },
    counts: { documents: 2, hearings: 7, links: 1, listings: 3, my_drafts: 0, notes: 4, orders: 5, timeline: 12 },
    court: { est_code: "GAHC01", name: "Principal Seat at Guwahati" },
    court_transfers: [{ from_court_text: "Court 1", to_court_text: "Court 3", transfer_date: "2026-03-01" }],
    custody: {
      can_recall: true,
      can_send: true,
      due_date: "2026-10-10",
      holder_office: { code: "EDU-DSE", name: "Secondary Education" },
      holder_user: { id: "u-7", full_name: "Officer One", designation: "SO" },
      leg_seq_no: 2,
      overdue: true,
      overdue_days: 2,
      pending_action: "prepare_reply",
      pending_action_label: "Prepare reply",
      reason: null,
      remark: "Please draft the affidavit",
      sent_by: { name: "Edu Admin", designation: "Under Secretary", office_code: "EDU" },
      since: "2026-10-01T10:00:00Z",
    },
    dossier_status: "fetched",
    identity: {
      cnr: "ASHC010012342026",
      court_est_name: "Gauhati High Court",
      case_type_id: null,
      case_type_text: "WP(C)",
      reg_no: 1234,
      reg_year: 2026,
      case_no_text: "WP(C)/1234/2026",
      filing_case_type_id: null,
      filing_case_type_text: "WP(C)",
      filing_no: 900,
      filing_year: 2026,
      filing_no_text: "WP(C)/900/2026",
      filing_date: "2026-01-10",
      registration_date: "2026-01-12",
      date_first_list: "2026-01-20",
    },
    lower_courts: [{ case_no_text: "OA 1/2025", court_name: "Tribunal", decision_date: "2025-12-01", level: "tribunal" }],
    merged_into_ref_no: null,
    objections: [{ seq: 1, scrutiny_date: "2026-01-11", objection: "Index missing", compliance_by_date: null, receipt_date: null }],
    ownership: {
      primary: { office_code: "EDU", office_name: "Education", unit: null, officer: null, claimed_at: "2026-09-01T10:00:00Z" },
      watchers: [],
    },
    parties: [
      { name: "RAM KUMAR", party_no: 1, role: "petitioner", address: null, has_legal_heir: null, is_current: true },
      { name: "STATE OF ASSAM", party_no: 1, role: "respondent", address: null, has_legal_heir: null, is_current: true },
      { name: "DIRECTOR", party_no: 2, role: "respondent", address: null, has_legal_heir: null, is_current: true },
    ],
    parties_as_printed: {
      petitioner_summary: "RAM KUMAR",
      respondent_summary: "STATE OF ASSAM AND 1 OTHER",
      pet_advocate: "A. Das",
      res_advocate: "SC, EDU",
    },
    place: {
      district_id: null,
      district_name_as_listed: "Kamrup",
      filing_district_code: 1,
      filing_state_code: 18,
      fir_no: null,
      fir_year: null,
      main_matter_text: null,
      police_st_code: null,
      police_station: null,
      state_id: null,
      state_name_as_listed: "Assam",
      uniform_code: null,
    },
    portal: {
      closed_at: null,
      created_at: "2026-01-20T10:00:00Z",
      created_by: null,
      dossier_stale: false,
      first_seen_source: "causelist",
      is_provisional: false,
      is_tracked: true,
      last_full_refresh_at: "2026-10-01T10:00:00Z",
      last_status_refresh_at: "2026-10-11T10:00:00Z",
      merged_into_case_id: null,
      updated_at: "2026-10-11T10:00:00Z",
      updated_by: null,
    },
    stage: { label: "Reply due", office_code: "EDU", phase: "pleadings", response_mode: "reply", set_at: "2026-10-01T10:00:00Z", stage: "reply_due" },
    status: {
      status: "pending",
      date_filing_disp: null,
      date_judgement_pronounced: null,
      date_judgement_reserved: null,
      disposal_date: null,
      disposal_nature: null,
      disposal_type: null,
      goshwara_no: "G-17",
      last_hearing_date: "2026-09-25",
      next_hearing_date: "2026-11-20",
      next_purpose: "For orders",
      reason_for_rej: null,
      short_order: null,
    },
    writ_info: [{ appellate_authority: "Division Bench", appellate_case_number: "WA/5/2026" }],
    ...extra,
  } as CaseDetail;
}

function actions(extra: Partial<OwnershipActions> = {}): OwnershipActions {
  return {
    claim: false,
    claim_departments: [],
    dismiss: false,
    suggest: false,
    allot: false,
    take_over: false,
    stop_watching: false,
    request_transfer: false,
    withdraw_transfer: false,
    decide_transfer: false,
    ...extra,
  };
}

function ownership(a: OwnershipActions, extra: Partial<CaseOwnershipView> = {}): CaseOwnershipView {
  return {
    primary: {
      id: "o-1",
      case: {} as CaseOwnershipView["watchers"][number]["case"],
      office_code: "EDU",
      role: "primary",
      status: "active",
      unit: { code: "EDU-DSE", name: "Secondary Education" },
      officer: { id: "u-8", full_name: "Officer Two" },
      claimed_at: "2026-09-01T10:00:00Z",
      allotted_at: null,
      released_at: null,
      release_reason: null,
    },
    watchers: [],
    recommendations: [],
    open_transfer: null,
    actions: a,
    ...extra,
  };
}

function me(functions: Permission[] = READ) {
  return makeMe(functions, "dept_admin", {
    memberships: [
      {
        id: "m-1",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: null,
        role: "dept_admin",
        is_primary: true,
        is_active: true,
        functions,
      },
    ],
  });
}

function overviewRoutes(c: CaseDetail, own: CaseOwnershipView | Response, functions: Permission[] = READ) {
  return {
    "GET /me": me(functions),
    [`GET ${BASE}`]: c,
    [`GET ${BASE}/ownership`]: own,
    [`GET ${BASE}/listings`]: { items: [], total: 0 },
    [`GET ${BASE}/hearings`]: { items: [], total: 0 },
    [`GET ${BASE}/orders`]: { items: [], total: 0 },
  };
}

beforeEach(() => {
  resetNav(BASE);
});

describe("the frame", () => {
  it("a 404 shows one neutral message", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: json(404, { detail: "no such case" }) });
    renderWithClient(
      <CaseFrame caseRef={REF}>
        <p>body</p>
      </CaseFrame>,
    );
    expect(await screen.findByText("No such case, or you do not have access to it.")).toBeInTheDocument();
    expect(screen.queryByText("body")).toBeNull();
  });

  it("a provisional case says so and shows no CNR", async () => {
    const c = detail({
      identity: { ...detail().identity, cnr: null },
      portal: { ...detail().portal, is_provisional: true },
    });
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: c });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    expect(await screen.findByText("Provisional — no CNR yet")).toBeInTheDocument();
    expect(screen.queryByText(/ASHC01/)).toBeNull();
  });

  it("a merged case links to the surviving case instead of tabs", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ merged_into_ref_no: "ASLMS/GOA/CASE/2026/000009" }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    expect(await screen.findByRole("link", { name: "Open ASLMS/GOA/CASE/2026/000009" })).toHaveAttribute(
      "href",
      "/cases/ASLMS-GOA-CASE-2026-000009",
    );
    expect(screen.queryByRole("navigation", { name: "Case sections" })).toBeNull();
  });

  it("Fetch from the court shows only when not fetched and with cases.search_court", async () => {
    const api = browserApi({
      "GET /me": me([...READ, "cases.search_court"]),
      [`GET ${BASE}`]: detail({ dossier_status: "not_fetched" }),
      [`POST ${BASE}/fetch-court`]: {},
    });
    const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    await userEvent.click(await screen.findByRole("button", { name: "Fetch from the court" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === `${BASE}/fetch-court`)).toBe(true));
    unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ dossier_status: "not_fetched" }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    expect(await screen.findByText("Court details not yet fetched.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fetch from the court" })).toBeNull();
  });

  it("tab badges come from counts; no Case Assistant, Upload or Hand over", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const tabs = await screen.findByRole("navigation", { name: "Case sections" });
    expect(within(tabs).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Hearings (7)" })).toHaveAttribute("href", `${BASE}/hearings`);
    expect(within(tabs).getByRole("link", { name: "Orders (5)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Notes (4)" })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: /Assistant/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Upload|Hand over|Assistant/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "WP(C)/1234/2026" })).toBeInTheDocument();
    expect(screen.getByText("ASHC010012342026")).toBeInTheDocument();
  });
});

describe("the overview and the ownership card", () => {
  it("the custody card is read-only and the basis line is shown", async () => {
    browserApi(overviewRoutes(detail(), ownership(actions())));
    renderWithClient(<Overview caseRef={REF} />);
    const custody = await screen.findByRole("region", { name: "Custody" });
    expect(within(custody).getByText("Prepare reply")).toBeInTheDocument();
    expect(within(custody).getByText("2 day(s) overdue")).toBeInTheDocument();
    expect(within(custody).getByText("Please draft the affidavit")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send|Recall/ })).toBeNull();
    expect(screen.getByText("You see this case as: owning department")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+ 1 more" })).toHaveAttribute("href", `${BASE}/parties`);
  });

  it("shows exactly the buttons whose actions flag is true, never a release", async () => {
    browserApi(overviewRoutes(detail(), ownership(actions({ allot: true, request_transfer: true }))));
    renderWithClient(<Overview caseRef={REF} />);
    const card = await screen.findByRole("region", { name: "Ownership" });
    await within(card).findByRole("button", { name: "Allot" });
    const buttons = within(card).getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual(["Allot", "Request transfer"]);
    expect(within(card).queryByRole("button", { name: /release|return|pool/i })).toBeNull();
  });

  it("claim with two departments asks which one", async () => {
    const api = browserApi({
      ...overviewRoutes(detail({ ownership: { primary: null, watchers: [] } }), ownership(actions({ claim: true, claim_departments: ["EDU", "HEALTH"] }), { primary: null })),
      [`POST ${BASE}/claim`]: json(201, {}),
    });
    renderWithClient(<Overview caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    const pick = within(dialog).getByLabelText("Claim for");
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a department", "EDU", "HEALTH"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    expect(within(dialog).getByText("Choose a department.")).toBeInTheDocument();
    await userEvent.selectOptions(pick, "HEALTH");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "HEALTH" }));
  });

  it("claim by the super admin lists every department", async () => {
    browserApi({
      ...overviewRoutes(detail(), ownership(actions({ claim: true, claim_departments: null }), { primary: null })),
      "GET /custody/recipients": { departments: [{ code: "EDU", name: "Education" }, { code: "FIN", name: "Finance" }], items: [], units: [], total: 2 },
    });
    renderWithClient(<Overview caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "FIN — Finance" })).toBeInTheDocument());
    expect(within(dialog).getByRole("option", { name: "EDU — Education" })).toBeInTheDocument();
  });

  it("take over sends the officer the screen showed", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ take_over: true }))),
      [`POST ${BASE}/take-over`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: "Take over" }));
    const dialog = screen.getByRole("dialog", { name: "Take over this case" });
    expect(within(dialog).getByText(/allotted to Officer Two/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Take over" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ expected_officer_user_id: "u-8" }),
    );
  });

  it("stop watching needs a reason", async () => {
    const view = ownership(actions({ stop_watching: true }), {
      primary: { ...ownership(actions()).primary!, office_code: "HEALTH" },
      watchers: [{ ...ownership(actions()).primary!, id: "o-2", role: "watcher", office_code: "EDU", officer: null, unit: null }],
    });
    const api = browserApi({ ...overviewRoutes(detail(), view), [`POST ${BASE}/stop-watching`]: {} });
    renderWithClient(<Overview caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: "Stop watching" }));
    const dialog = screen.getByRole("dialog", { name: "Stop watching this case" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop watching" }));
    expect(within(dialog).getByText("A reason is required.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Reason (required)"), "no longer ours");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop watching" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ reason: "no longer ours" }));
  });

  it("a transfer request sends stay_as_watcher", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ request_transfer: true }))),
      "GET /custody/recipients": { departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }], items: [], units: [], total: 2 },
      [`POST ${BASE}/transfers`]: json(201, {}),
    });
    renderWithClient(<Overview caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: "Request transfer" }));
    const dialog = screen.getByRole("dialog", { name: "Request a transfer" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await userEvent.type(within(dialog).getByLabelText("Reason (required)"), "health matter");
    await userEvent.click(within(dialog).getByLabelText("Stay as a watcher after the transfer"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Request transfer" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        to_office_code: "HEALTH",
        reason: "health matter",
        stay_as_watcher: true,
      }),
    );
  });
});

describe("tabs", () => {
  it("orders offer View and Download by function and file state", async () => {
    browserApi({
      "GET /me": me(["cases.view_scope", "documents.view"]),
      [`GET ${BASE}/orders`]: {
        items: [
          { id: "o-1", order_no: "3", order_date: "2026-09-25", kind: "interim", order_judge_name: "X", download_status: "stored", document_id: "d-1", order_details: null, is_reportable: null, date_judgement_pronounced: null, date_judgement_reserved: null },
          { id: "o-2", order_no: "2", order_date: "2026-09-01", kind: "interim", order_judge_name: null, download_status: "pending", document_id: null, order_details: null, is_reportable: null, date_judgement_pronounced: null, date_judgement_reserved: null },
          { id: "o-3", order_no: "1", order_date: "2026-08-01", kind: "interim", order_judge_name: null, download_status: "not_available", document_id: null, order_details: null, is_reportable: null, date_judgement_pronounced: null, date_judgement_reserved: null },
        ],
        total: 3,
      },
    });
    renderWithClient(<Orders caseRef={REF} />);
    const view = await screen.findByRole("link", { name: "View" });
    expect(view).toHaveAttribute("href", `/api/backend${BASE}/orders/o-1/file?disposition=inline`);
    expect(view).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("link", { name: "Download" })).toBeNull(); // no documents.download
    expect(screen.getByText("fetch pending")).toBeInTheDocument();
    expect(screen.getByText("not yet published")).toBeInTheDocument();
  });

  it("documents are grouped with the assistant and visibility badges", async () => {
    const doc = (id: string, group: string, extra: Partial<DocumentItem> = {}): DocumentItem =>
      ({
        id,
        doc_group: group,
        doc_type: "affidavit",
        doc_type_label: group === "court_record" ? "Order" : "Affidavit",
        doc_date: "2026-09-01",
        description: `${id} description`,
        original_filename: `${id}.pdf`,
        mime: "application/pdf",
        size_bytes: 2048,
        page_count: 3,
        uploaded_by: { name: "Edu Admin", office_code: "EDU", designation: null },
        office: null,
        visibility: "case_scope",
        assistant_available: group !== "internal",
        sourcetrace_status: group === "internal" ? "not_applicable" : "ingested",
        text_status: "extracted",
        archived_at: null,
        ...extra,
      }) as DocumentItem;
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/documents`]: {
        items: [
          doc("d-1", "court_record"),
          doc("d-2", "internal", { visibility: "private_to_office", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }),
        ],
        total: 2,
      },
    });
    renderWithClient(<Documents caseRef={REF} />);
    const orders = await screen.findByRole("region", { name: "Court orders" });
    expect(within(orders).getByText("In Case Assistant")).toBeInTheDocument();
    const internal = screen.getByRole("region", { name: "Internal documents" });
    expect(within(internal).getByText("Not sent to SourceTrace")).toBeInTheDocument();
    expect(within(internal).getByText("Private to the office")).toBeInTheDocument();
    expect(within(internal).queryByRole("link", { name: "View" })).toBeNull(); // Word: download only
    expect(within(internal).getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/backend/documents/d-2/file?disposition=attachment",
    );
    expect(screen.queryByRole("region", { name: "Court filings" })).toBeNull();
  });

  it("notes link corrections both ways and hide corrected notes on request", async () => {
    const note = (seq: number, extra: Partial<Note> = {}): Note =>
      ({
        id: `n-${seq}`,
        ref_no: `ASLMS/EDU/NOTE/2026/00000${seq}`,
        seq_no: seq,
        kind: "remark",
        kind_label: "Remark",
        body: `body ${seq}`,
        author: { name: "Edu Admin", designation: "Under Secretary", office_code: "EDU", role: "dept_admin" },
        created_at: "2026-10-01T10:00:00Z",
        visibility: "case_scope",
        attachments: [],
        supersedes: null,
        superseded_by: null,
        custody_leg_seq_no: null,
        drafted_at: null,
        ...extra,
      }) as Note;
    const api = browserApi({
      "GET /me": me(),
      [`GET ${BASE}/notes`]: (call: { url: string }) =>
        call.url.includes("include_superseded=false")
          ? { items: [note(2, { supersedes: { ref_no: "ASLMS/EDU/NOTE/2026/000001", seq_no: 1 } })], total: 1 }
          : {
              items: [
                note(1, { superseded_by: { ref_no: "ASLMS/EDU/NOTE/2026/000002", seq_no: 2 } }),
                note(2, { supersedes: { ref_no: "ASLMS/EDU/NOTE/2026/000001", seq_no: 1 } }),
              ],
              total: 2,
            },
    });
    renderWithClient(<Notes caseRef={REF} />);
    expect(await screen.findByRole("link", { name: "corrected by ASLMS/EDU/NOTE/2026/000002" })).toHaveAttribute("href", "#note-2");
    expect(screen.getByRole("link", { name: "corrects ASLMS/EDU/NOTE/2026/000001" })).toHaveAttribute("href", "#note-1");
    await userEvent.click(screen.getByLabelText("Hide corrected notes"));
    await waitFor(() => expect(screen.queryByText("body 1")).toBeNull());
    expect(api.calls.some((c) => c.url.includes("include_superseded=false"))).toBe(true);
  });

  it("the Details tab renders every block of the overview", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<Details caseRef={REF} />);
    for (const title of [
      "Identity",
      "Status",
      "Classification",
      "Place",
      "As printed",
      "Acts and sections",
      "Lower courts",
      "Applications",
      "Objections",
      "Court transfers",
      "Writ information",
      "In the portal",
    ]) {
      expect(await screen.findByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText("G-17")).toBeInTheDocument(); // goshwara
    expect(screen.getByText("WA/5/2026")).toBeInTheDocument(); // writ information
    expect(screen.getByText("Index missing")).toBeInTheDocument(); // objections
  });

  it("linked cases: hidden ones are text, the graph draws nodes and edges and says when truncated", async () => {
    const visibleCase = { id: "c-2", ref_no: "ASLMS/GOA/CASE/2026/000002", cnr: "ASHC010000022026", case_no_text: "WA/2/2026", is_provisional: false, petitioner_summary: null, respondent_summary: null, status: "pending", next_hearing_date: null, last_listed_on: null, last_listing: null };
    const hiddenCase = { ...visibleCase, id: "c-3", ref_no: "ASLMS/GOA/CASE/2026/000003", case_no_text: "WP(C)/3/2026" };
    const api = browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/links`]: {
        items: [
          { direction: "out", kind: "appeal", case: visibleCase, case_no_text: "WA/2/2026", cnr: visibleCase.cnr, filing_number_text: null, source: "dossier", visible: true },
          { direction: "in", kind: "connected", case: hiddenCase, case_no_text: "WP(C)/3/2026", cnr: null, filing_number_text: null, source: "causelist", visible: false },
        ],
      },
      [`GET ${BASE}/links/graph`]: {
        nodes: [
          { key: "c-1", case: { ...visibleCase, id: "c-1", ref_no: "ASLMS/GOA/CASE/2026/000001", case_no_text: "WP(C)/1234/2026" }, case_no_text: "WP(C)/1234/2026", visible: true },
          { key: "c-2", case: visibleCase, case_no_text: "WA/2/2026", visible: true },
          { key: "c-3", case: hiddenCase, case_no_text: "WP(C)/3/2026", visible: false },
        ],
        edges: [
          { from: "c-1", to: "c-2", kind: "appeal" },
          { from: "c-3", to: "c-1", kind: "connected" },
        ],
        truncated: true,
      },
    });
    const { container } = renderWithClient(<Links caseRef={REF} />);
    const table = await screen.findByRole("table", { name: "Linked cases" });
    expect(within(table).getByRole("link", { name: "WA/2/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-000002");
    expect(within(table).getByText("WP(C)/3/2026").closest("a")).toBeNull();
    await screen.findByText("The graph is cut short; not every connected case is drawn.");
    expect(container.querySelectorAll("[data-node]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-edge]")).toHaveLength(2);
    const svg = screen.getByRole("img", { name: "Relationship graph" });
    expect(within(svg).getByRole("link", { name: "WA/2/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-000002");
    expect(within(svg).queryByRole("link", { name: "WP(C)/3/2026" })).toBeNull();
    expect(api.calls.some((c) => c.url.includes("/links/graph?depth=2"))).toBe(true);
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseDetail, CaseOwnershipView, DocumentItem, Note, Ownership, OwnershipActions, Permission } from "@/lib/api/types";
import { caseDetail as detail } from "@/test/caseDetail";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, PRIMARY_SELECTOR, renderWithClient } from "@/test/render";
import { CustodyTab } from "@/components/workflow/CustodyTab";

import { CaseFrame } from "./CaseFrame";
import { Details } from "./Details";
import { Documents } from "./Documents";
import { Hearings } from "./Hearings";
import { Links } from "./Links";
import { Notes } from "./Notes";
import { Orders } from "./Orders";
import { Overview } from "./Overview";
import { Parties } from "./Parties";
import { Timeline } from "./Timeline";

const REF = "ASLMS-GHC-CASE-2026-000001";
const BASE = `/cases/${REF}`;
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download"];

function actions(extra: Partial<OwnershipActions> = {}): OwnershipActions {
  return {
    claim: false,
    claim_departments: [],
    dismiss: false,
    dismiss_departments: [],
    suggest: false,
    suggest_departments: [],
    allot: false,
    allot_departments: [],
    take_over: false,
    take_over_departments: [],
    stop_watching: false,
    stop_watching_departments: [],
    request_transfer: false,
    transfer_from: null,
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

/** The Overview folds today's Ownership card under "Ownership and recommendations" (portal-ui-redesign, decision 24). */
async function openOwnership() {
  await userEvent.click(await screen.findByRole("button", { name: "Ownership and Recommendations" }));
}

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
    expect(await screen.findByText("Provisional — No CNR Yet")).toBeInTheDocument();
    expect(screen.queryByText(/ASHC01/)).toBeNull();
  });

  it("a merged case links to the surviving case instead of tabs", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ merged_into_ref_no: "ASLMS/GHC/CASE/2026/000009" }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    expect(await screen.findByRole("link", { name: "Open ASLMS/GHC/CASE/2026/000009" })).toHaveAttribute(
      "href",
      "/cases/ASLMS-GHC-CASE-2026-000009",
    );
    expect(screen.queryByRole("navigation", { name: "Case Sections" })).toBeNull();
  });

  it("Fetch from the court shows only when not fetched and with cases.search_court", async () => {
    const api = browserApi({
      "GET /me": me([...READ, "cases.search_court"]),
      [`GET ${BASE}`]: detail({ dossier_status: "not_fetched" }),
      [`POST ${BASE}/fetch-court`]: {},
    });
    const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    await userEvent.click(await screen.findByRole("button", { name: "Fetch From the Court" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === `${BASE}/fetch-court`)).toBe(true));
    unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ dossier_status: "not_fetched" }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    expect(await screen.findByText("Court details not yet fetched.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fetch From the Court" })).toBeNull();
  });

  it("six tabs with counts and More (Parties, Linked cases, Journey and stage, Alerts, Details); no Case Assistant", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const tabs = await screen.findByRole("navigation", { name: "Case Sections" });
    expect(within(tabs).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Hearings (7)" })).toHaveAttribute("href", `${BASE}/hearings`);
    expect(within(tabs).getByRole("link", { name: "Orders (5)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Documents (2)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Notes (4)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Timeline (12)" })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: "Journey and Stage" })).toBeNull();
    await userEvent.click(within(tabs).getByRole("button", { name: "More" }));
    const more = within(tabs).getByRole("menu");
    expect(within(more).getAllByRole("menuitem").map((m) => m.textContent)).toEqual([
      "Parties",
      "Linked Cases",
      "Journey and Stage",
      "Alerts",
      "Details",
    ]);
    expect(within(more).getByRole("menuitem", { name: "Journey and Stage" })).toHaveAttribute("href", `${BASE}/custody`);
    expect(within(more).getByRole("menuitem", { name: "Alerts" })).toHaveAttribute("href", `${BASE}/alerts`);
    expect(within(tabs).queryByRole("link", { name: /Assistant/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Hand over|Assistant/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "WP(C)/1234/2026", level: 1 })).toBeInTheDocument();
  });

  it("the More menu shows the current tab's label when one of its tabs is open", async () => {
    resetNav(`${BASE}/custody`);
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const tabs = await screen.findByRole("navigation", { name: "Case Sections" });
    expect(within(tabs).getByRole("button", { name: "Journey and Stage" })).toHaveAttribute("aria-haspopup", "menu");
    expect(within(tabs).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("the summary header shows the five facts and the badges (case-workspace-admin, decision 9)", async () => {
    const c = detail({
      custody: { ...detail().custody!, holder_user: { id: "u-1", full_name: "Anita Sharma", designation: "Under Secretary" } },
      status: { ...detail().status, next_hearing_date: "2026-11-20" },
    });
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: c,
      [`GET ${BASE}/listings`]: {
        items: [{ list_date: "2026-11-20", court_no: "3", sr_no: 14, list_type: "daily", source: "causelist" }],
        total: 1,
      },
    });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const header = await screen.findByRole("region", { name: "Case Summary" });
    // the status label is the badge and the Status fact (hidden on phones)
    expect(within(header).getAllByText("Pending")).toHaveLength(2);
    expect(await within(header).findByText("Your Department")).toBeInTheDocument();
    // the case is with the caller and overdue: "Overdue since <date>" in danger
    expect(await within(header).findByText("Overdue since 10 Oct 2026")).toBeInTheDocument();
    expect(within(header).getByText(/RAM KUMAR/)).toBeInTheDocument();
    const fact = (label: string) => within(header).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
    // the date always shows with the whole-day countdown (owner, 23 Oct 2026)
    await waitFor(() => expect(fact("Next Hearing")).toHaveTextContent(/^Fri, 20 Nov 2026( · (today|tomorrow|in [0-9]+ days))? · Court 3, item 14/));
    expect(fact("With")).toHaveTextContent("Under Secretary, Secondary Education (you)");
    expect(fact("Stage")).toHaveTextContent("Reply due");
    expect(fact("Owner Department")).toHaveTextContent("Education");
    expect(fact("Status")).toHaveTextContent("Pending");
    expect(within(header).getByText("Status", { selector: "dt" }).parentElement).toHaveAttribute("data-fact", "status");
    expect(within(header).queryByText("File is with")).toBeNull();
  });

  it("Action due shows only when the case is with the caller and has a due date (decision 9)", async () => {
    const mine = { ...detail().custody!, holder_user: { id: "u-1", full_name: "Anita Sharma", designation: "Under Secretary" } };
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ custody: { ...mine, overdue: false, overdue_days: 0, due_date: "2099-01-05" } }) });
    let view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    let header = await screen.findByRole("region", { name: "Case Summary" });
    expect(await within(header).findByText("Action due 5 Jan 2099")).toBeInTheDocument();
    view.unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ custody: { ...mine, due_date: null, overdue: false } }) });
    view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    header = await screen.findByRole("region", { name: "Case Summary" });
    expect(within(header).queryByText(/Action due|Overdue since/)).toBeNull();
    view.unmount();
    // with a colleague: no badge
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    header = await screen.findByRole("region", { name: "Case Summary" });
    expect(within(header).queryByText(/Action due|Overdue since/)).toBeNull();
  });

  it("another department's owner shows its code; the case is with a colleague; no owner says Not claimed", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail({
        ownership: { primary: { office_code: "HEALTH", office_name: "Health", unit: null, officer: null, claimed_at: "2026-09-01T10:00:00Z" }, watchers: [] },
      }),
    });
    const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const header = await screen.findByRole("region", { name: "Case Summary" });
    expect(within(header).getByText("HEALTH")).toBeInTheDocument();
    expect(within(header).queryByText("Your Department")).toBeNull();
    const fact = (label: string) => within(header).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
    expect(fact("With")).toHaveTextContent("SO, Secondary Education");
    expect(fact("With").firstElementChild).toHaveAttribute("title", "Officer One");
    unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ ownership: { primary: null, watchers: [] }, custody: null, stage: null }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const bare = await screen.findByRole("region", { name: "Case Summary" });
    const fact2 = (label: string) => within(bare).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
    expect(fact2("Owner Department")).toHaveTextContent("Not Claimed");
    expect(fact2("Stage")).toHaveTextContent("No stage set.");
    expect(fact2("With")).toHaveTextContent("—");
  });

  it("one primary action, picked from the flags: Send case, else Claim, else Accept transfer", async () => {
    const primaries = () => document.querySelectorAll("[data-variant='primary']");
    // Send case by custody.can_send; Recall case in More actions by can_recall
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail(), [`GET ${BASE}/ownership`]: ownership(actions({ claim: true, claim_departments: ["EDU"] })) });
    let view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    let group = await screen.findByRole("group", { name: "Case Actions" });
    expect(within(group).getByRole("button", { name: "Send Case" })).toBeInTheDocument();
    expect(within(group).queryByRole("button", { name: "Claim" })).toBeNull();
    await waitFor(() => expect(within(group).getByRole("button", { name: "More Actions" })).toBeInTheDocument());
    await userEvent.click(within(group).getByRole("button", { name: "More Actions" }));
    expect(within(group).getByRole("menuitem", { name: "Recall Case" })).toBeInTheDocument();
    // the claim that is not primary waits in the menu
    await waitFor(() => expect(within(group).getByRole("menuitem", { name: "Claim" })).toBeInTheDocument());
    expect(primaries()).toHaveLength(1);
    view.unmount();
    // nothing to send: Claim is the primary
    const noSend = { ...detail().custody!, can_send: false, can_recall: false };
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail({ custody: noSend }),
      [`GET ${BASE}/ownership`]: ownership(actions({ claim: true, claim_departments: ["EDU"] }), { primary: null }),
    });
    view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    group = await screen.findByRole("group", { name: "Case Actions" });
    expect(await within(group).findByRole("button", { name: "Claim" })).toBeInTheDocument();
    expect(within(group).queryByRole("button", { name: "Send Case" })).toBeNull();
    view.unmount();
    // nothing else: Accept transfer by decide_transfer
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail({ custody: noSend }),
      [`GET ${BASE}/ownership`]: ownership(actions({ decide_transfer: true }), {
        open_transfer: { id: "t-1", ref_no: "ASLMS-EDU-TRF-2026-000001", from_office_code: "HEALTH", to_office_code: "EDU", status: "requested", reason: "ours", requested_at: "2026-10-01T10:00:00Z" } as CaseOwnershipView["open_transfer"],
      }),
    });
    view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    group = await screen.findByRole("group", { name: "Case Actions" });
    expect(await within(group).findByRole("button", { name: "Accept Transfer" })).toBeInTheDocument();
    view.unmount();
    // a reader with no action sees no button at all
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ custody: noSend }), [`GET ${BASE}/ownership`]: json(404, { detail: "no" }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    group = await screen.findByRole("group", { name: "Case Actions" });
    await new Promise((r) => setTimeout(r, 20));
    expect(within(group).queryAllByRole("button")).toHaveLength(0);
  });

  it("Add note, Upload and Set stage are the rail's Quick actions only; Enter next date sits in More actions (case-workspace-admin, decisions 9 and 12)", async () => {
    const noSend = { ...detail().custody!, can_send: false, can_recall: false };
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail({ custody: noSend, workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: true } }),
      "GET /workflow/codes": { note_kinds: [], pending_actions: [], stages: [], response_modes: [], custody_reasons: [], limits: { note_max_chars: 100, attachments_max_files: 2, note_drafts_max: 5 } },
    });
    const view = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const group = await screen.findByRole("group", { name: "Case Actions" });
    expect(within(group).queryByRole("button", { name: "Add Note" })).toBeNull();
    await userEvent.click(within(group).getByRole("button", { name: "More Actions" }));
    expect(within(group).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Enter Next Date"]);
    await userEvent.keyboard("{Escape}");
    // below 1100 px the Quick actions card is closed, its title line saying how many actions it holds
    const quick = screen.getByRole("region", { name: "Quick Actions" });
    await userEvent.click(within(quick).getByRole("button", { name: /Quick Actions\s*3 actions/ }));
    expect(within(quick).getAllByRole("button").slice(1).map((b) => b.textContent)).toEqual(["Add Note", "Upload a Document", "Set Stage"]);
    await userEvent.click(within(quick).getByRole("button", { name: "Add Note" }));
    const dialog = screen.getByRole("dialog", { name: "Add a Note" });
    expect(within(dialog).getByText("WP(C)/1234/2026")).toBeInTheDocument();
    expect(within(dialog).getByText(/becomes part of the case record at once/)).toBeInTheDocument();
    view.unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail({ custody: noSend }) });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const none = await screen.findByRole("group", { name: "Case Actions" });
    expect(screen.queryByRole("button", { name: "Add Note" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Quick Actions" })).toBeNull();
    expect(within(none).queryByRole("button", { name: "More Actions" })).toBeNull();
  });
});

describe("the overview and the ownership card", () => {
  it("Latest order and Recent activity, the folded parties and the basis line (portal-ui-redesign, decision 24)", async () => {
    const events = Array.from({ length: 5 }, (_, i) => ({
      type: "custody_moved",
      label: `Event ${i + 1}`,
      occurred_at: `2026-10-1${i}T10:00:00Z`,
      actor_name: "Edu Admin",
      payload: {},
    }));
    browserApi({
      ...overviewRoutes(detail(), ownership(actions())),
      [`GET ${BASE}/timeline`]: { items: events, total: 12 },
      [`GET ${BASE}/orders`]: {
        items: [
          { id: "o-1", order_no: "3", order_date: "2026-09-25", kind: "interim", order_judge_name: "X", download_status: "stored", document_id: "d-1", order_details: "Affidavit within four weeks.", is_reportable: null, date_judgement_pronounced: null, date_judgement_reserved: null },
        ],
        total: 1,
      },
    });
    renderWithClient(<Overview caseRef={REF} />);
    const latest = await screen.findByRole("region", { name: "Latest Order" });
    expect(await within(latest).findByText("Affidavit within four weeks.")).toBeInTheDocument();
    expect(within(latest).getByRole("link", { name: "All Orders →" })).toHaveAttribute("href", `${BASE}/orders`);
    const recent = await screen.findByRole("region", { name: "Recent Activity" });
    const list = await within(recent).findByRole("list", { name: "Recent Activity" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(within(recent).getByRole("link", { name: "Timeline →" })).toHaveAttribute("href", `${BASE}/timeline`);
    // the parties, advocates and acts are folded away until asked for
    const fold = within(latest).getByRole("button", { name: "Show Parties, Advocates and Acts" });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(within(latest).getByText("A. Das")).toBeInTheDocument();
    expect(within(latest).getByText("SC,EDU")).toBeInTheDocument();
    expect(within(latest).getByText("Constitution of India, 226")).toBeInTheDocument();
    expect(within(latest).getByRole("link", { name: "+ 1 more" })).toHaveAttribute("href", `${BASE}/parties`);
    expect(screen.getByText("You see this case as: owning department")).toBeInTheDocument();
    // no custody or stage card on the Overview any more: those facts are in the summary header
    expect(screen.queryByRole("region", { name: "Custody" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Stage" })).toBeNull();
  });

  it("shows exactly the buttons whose actions flag is true, never a release", async () => {
    browserApi(
      overviewRoutes(
        detail(),
        ownership(actions({ allot: true, allot_departments: ["EDU"], request_transfer: true, transfer_from: "EDU" })),
      ),
    );
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    const card = await screen.findByRole("region", { name: "Ownership" });
    await within(card).findByRole("button", { name: "Assign" });
    const buttons = within(card).getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual(["Assign", "Request Transfer"]);
    expect(within(card).queryByRole("button", { name: /release|return|pool/i })).toBeNull();
  });

  it("OwnershipCard labels: Responsible unit and Dealing officer; an empty part is omitted (claim-assign-wording, decision 4)", async () => {
    const view = ownership(actions(), {
      watchers: [{ ...ownership(actions()).primary!, id: "o-2", role: "watcher", office_code: "HEALTH", unit: null, officer: null }],
    });
    browserApi(overviewRoutes(detail(), view));
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    const card = await screen.findByRole("region", { name: "Ownership" });
    const primary = (await within(card).findByText("Officer Two", { exact: false })).closest("li, p, div")!;
    expect(primary.textContent).toContain("Responsible unit EDU-DSE");
    expect(primary.textContent).toContain("Dealing officer Officer Two");
    expect(card.textContent).not.toMatch(/allot/i);
    // the HEALTH watcher has neither: no label shows for it
    const labels = card.textContent!.match(/Responsible unit|Dealing officer/g) ?? [];
    expect(labels).toEqual(["Responsible unit", "Dealing officer"]);
  });

  it("claim with two departments asks which one", async () => {
    const api = browserApi({
      ...overviewRoutes(detail({ ownership: { primary: null, watchers: [] } }), ownership(actions({ claim: true, claim_departments: ["EDU", "HEALTH"] }), { primary: null })),
      [`POST ${BASE}/claim`]: json(201, {}),
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim This Case" });
    const pick = within(dialog).getByLabelText("Claim For");
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a Department", "EDU", "HEALTH"]);
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
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim This Case" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "FIN — Finance" })).toBeInTheDocument());
    expect(within(dialog).getByRole("option", { name: "EDU — Education" })).toBeInTheDocument();
  });

  it("take over sends the department and the officer the screen showed", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ take_over: true, take_over_departments: ["EDU"] }))),
      [`POST ${BASE}/take-over`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Take Over" }));
    const dialog = screen.getByRole("dialog", { name: "Take Over This Case" });
    expect(within(dialog).getByText(/Officer Two is the dealing officer\. Take the case over\?/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Take Over" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "EDU", expected_officer_user_id: "u-8" }),
    );
  });

  it("stop watching needs a reason", async () => {
    const view = ownership(actions({ stop_watching: true, stop_watching_departments: ["EDU"] }), {
      primary: { ...ownership(actions()).primary!, office_code: "HEALTH" },
      watchers: [{ ...ownership(actions()).primary!, id: "o-2", role: "watcher", office_code: "EDU", officer: null, unit: null }],
    });
    const api = browserApi({ ...overviewRoutes(detail(), view), [`POST ${BASE}/stop-watching`]: {} });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Stop Watching" }));
    const dialog = screen.getByRole("dialog", { name: "Stop Watching This Case" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    expect(within(dialog).getByText("A reason is required.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "no longer ours");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "EDU", reason: "no longer ours" }),
    );
  });

  it("a transfer request sends stay_as_watcher and never offers the department it comes from", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ request_transfer: true, transfer_from: "EDU" }))),
      "GET /custody/recipients": { departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }], items: [], units: [], total: 2 },
      [`POST ${BASE}/transfers`]: json(201, {}),
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Request Transfer" }));
    const dialog = screen.getByRole("dialog", { name: "Request a Transfer" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    expect(within(dialog).queryByRole("option", { name: "EDU — Education" })).toBeNull();
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "health matter");
    await userEvent.click(within(dialog).getByLabelText("Stay as a watcher after the transfer"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Request Transfer" }));
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
  it("orders are collapsible rows: Print and Download PDF by function, the PDF inline once, and the file state", async () => {
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
    const rows = await screen.findAllByRole("button", { name: /interim/ });
    expect(rows).toHaveLength(3);
    // the date leads each row in the fixed column
    expect(within(rows[0]!).getByText("25 Sep 2026")).toBeInTheDocument();
    expect(screen.getByText("Judge: X")).toBeInTheDocument();
    expect(document.querySelector("iframe")).toBeNull();
    await userEvent.click(rows[0]!);
    const print = screen.getByRole("link", { name: "Print" });
    expect(print).toHaveAttribute("href", `/api/backend${BASE}/orders/o-1/file?disposition=inline`);
    expect(print).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("link", { name: "Download PDF" })).toBeNull(); // no documents.download
    expect(document.querySelectorAll("iframe")).toHaveLength(1);
    await userEvent.click(rows[1]!);
    expect(screen.getByText("fetch pending")).toBeInTheDocument();
    await userEvent.click(rows[2]!);
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
    const byGroup: Record<string, DocumentItem[]> = {
      court_record: [doc("d-1", "court_record")],
      court_filing: [],
      internal: [doc("d-2", "internal", { visibility: "private_to_office", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })],
    };
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/documents`]: (call: { url: string }) => {
        const g = new URL(call.url, "http://x").searchParams.get("group") ?? "";
        return { items: byGroup[g] ?? [], total: (byGroup[g] ?? []).length };
      },
    });
    renderWithClient(<Documents caseRef={REF} />);
    const orders = await screen.findByRole("region", { name: "Court Orders" });
    expect(within(orders).getByText("In Case Assistant")).toBeInTheDocument();
    const internal = screen.getByRole("region", { name: "Internal Documents" });
    expect(within(internal).getByText("Not Sent to SourceTrace")).toBeInTheDocument();
    expect(within(internal).getByText("Private to the Office")).toBeInTheDocument();
    expect(within(internal).queryByRole("link", { name: "View" })).toBeNull(); // Word: download only
    expect(within(internal).getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/backend/documents/d-2/file?disposition=attachment",
    );
    expect(screen.queryByRole("region", { name: "Court Filings" })).toBeNull();
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
    await userEvent.click(screen.getByLabelText("Hide Corrected Notes"));
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
      "As Printed",
      "Acts and Sections",
      "Lower Courts",
      "Applications",
      "Objections",
      "Court Transfers",
      "Writ Information",
      "In the Portal",
    ]) {
      expect(await screen.findByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText("G-17")).toBeInTheDocument(); // goshwara
    expect(screen.getByText("WA/5/2026")).toBeInTheDocument(); // writ information
    expect(screen.getByText("Index missing")).toBeInTheDocument(); // objections
  });

  it("linked cases: hidden ones are text, the graph draws nodes and edges and says when truncated", async () => {
    const visibleCase = { id: "c-2", ref_no: "ASLMS/GHC/CASE/2026/000002", cnr: "ASHC010000022026", case_no_text: "WA/2/2026", is_provisional: false, petitioner_summary: null, respondent_summary: null, status: "pending", next_hearing_date: null, last_listed_on: null, last_listing: null };
    const hiddenCase = { ...visibleCase, id: "c-3", ref_no: "ASLMS/GHC/CASE/2026/000003", case_no_text: "WP(C)/3/2026" };
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
          { key: "c-1", case: { ...visibleCase, id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", case_no_text: "WP(C)/1234/2026" }, case_no_text: "WP(C)/1234/2026", visible: true },
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
    const table = await screen.findByRole("table", { name: "Linked Cases" });
    expect(within(table).getByRole("link", { name: "WA/2/2026" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000002");
    expect(within(table).getByText("WP(C)/3/2026").closest("a")).toBeNull();
    await screen.findByText("The graph is cut short; not every connected case is drawn.");
    expect(container.querySelectorAll("[data-node]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-edge]")).toHaveLength(2);
    const svg = screen.getByRole("img", { name: "Relationship Graph" });
    expect(within(svg).getByRole("link", { name: "WA/2/2026" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000002");
    expect(within(svg).queryByRole("link", { name: "WP(C)/3/2026" })).toBeNull();
    expect(api.calls.some((c) => c.url.includes("/links/graph?depth=2"))).toBe(true);
  });
});

// ------------------------------------------------------------------------------------------------ portal-cases-followups

const DEPTS = {
  departments: [
    { code: "EDU", name: "Education" },
    { code: "HEALTH", name: "Health" },
    { code: "FIN", name: "Finance" },
    { code: "REV", name: "Revenue" },
  ],
  items: [],
  units: [],
  total: 4,
};

function primaryRow(extra: Partial<Ownership> = {}): Ownership {
  return { ...ownership(actions()).primary!, ...extra };
}

/** EDU primary (unit EDU-DSE, Officer Two) and HEALTH watcher (no unit, Health Officer). */
function twoRows(a: OwnershipActions): CaseOwnershipView {
  return ownership(a, {
    watchers: [
      primaryRow({ id: "o-2", role: "watcher", office_code: "HEALTH", unit: null, officer: { id: "u-9", full_name: "Health Officer" } }),
    ],
  });
}

function posted(api: ReturnType<typeof browserApi>, path: string): unknown[] {
  return api.calls.filter((c) => c.method === "POST" && c.path === path).map((c) => c.body);
}

describe("the department that acts (portal-cases-followups)", () => {
  it("dismiss with one department names it and sends it without asking", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ dismiss: true, dismiss_departments: ["EDU"] }))),
      [`POST ${BASE}/dismiss`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    const dialog = screen.getByRole("dialog", { name: "Dismiss This Recommendation" });
    expect(within(dialog).getByText("EDU")).toBeInTheDocument();
    expect(within(dialog).queryByRole("combobox")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(posted(api, `${BASE}/dismiss`)).toEqual([{ office_code: "EDU" }]));
  });

  it("dismiss with two departments asks, with nothing pre-selected, and sends the chosen one", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ dismiss: true, dismiss_departments: ["EDU", "HEALTH"] }))),
      [`POST ${BASE}/dismiss`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    const dialog = screen.getByRole("dialog", { name: "Dismiss This Recommendation" });
    const pick = within(dialog).getByLabelText("For");
    expect(pick).toHaveValue("");
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a Department", "EDU", "HEALTH"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    expect(within(dialog).getByText("Choose a department.")).toBeInTheDocument();
    expect(posted(api, `${BASE}/dismiss`)).toEqual([]);
    await userEvent.selectOptions(pick, "HEALTH");
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(posted(api, `${BASE}/dismiss`)).toEqual([{ office_code: "HEALTH" }]));
  });

  it("an office_required answer opens the department choice instead of failing", async () => {
    let n = 0;
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ stop_watching: true, stop_watching_departments: ["EDU"] }))),
      [`POST ${BASE}/stop-watching`]: () =>
        n++ === 0
          ? json(400, { detail: { code: "office_required", message: "office_code is required", candidates: ["EDU", "HEALTH"] } })
          : {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Stop Watching" }));
    const dialog = screen.getByRole("dialog", { name: "Stop Watching This Case" });
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "not ours");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    const pick = await within(dialog).findByLabelText("For");
    expect(pick).toHaveValue("");
    await userEvent.selectOptions(pick, "HEALTH");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    await waitFor(() =>
      expect(posted(api, `${BASE}/stop-watching`)).toEqual([
        { office_code: "EDU", reason: "not ours" },
        { office_code: "HEALTH", reason: "not ours" },
      ]),
    );
  });

  it("stop watching with two departments asks which one", async () => {
    const view = ownership(actions({ stop_watching: true, stop_watching_departments: ["EDU", "HEALTH"] }), {
      primary: primaryRow({ office_code: "FIN" }),
      watchers: [
        primaryRow({ id: "o-2", role: "watcher", office_code: "EDU" }),
        primaryRow({ id: "o-3", role: "watcher", office_code: "HEALTH" }),
      ],
    });
    const api = browserApi({ ...overviewRoutes(detail(), view), [`POST ${BASE}/stop-watching`]: {} });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Stop Watching" }));
    const dialog = screen.getByRole("dialog", { name: "Stop Watching This Case" });
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "done");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    expect(within(dialog).getByText("Choose a department.")).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("For"), "EDU");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop Watching" }));
    await waitFor(() => expect(posted(api, `${BASE}/stop-watching`)).toEqual([{ office_code: "EDU", reason: "done" }]));
  });

  it("suggest leaves out the from department and the holders, and sends from_office_code", async () => {
    const view = ownership(actions({ suggest: true, suggest_departments: ["EDU", "HEALTH"] }), {
      primary: primaryRow({ office_code: "FIN" }),
    });
    const api = browserApi({
      ...overviewRoutes(detail(), view),
      "GET /custody/recipients": DEPTS,
      [`POST ${BASE}/suggest`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Suggest Department" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest Another Department" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Suggest From"), "HEALTH");
    const target = within(dialog).getByLabelText("Department");
    await waitFor(() => expect(within(target).getByRole("option", { name: "EDU — Education" })).toBeInTheDocument());
    expect(within(target).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose a Department",
      "EDU — Education",
      "REV — Revenue",
    ]);
    await userEvent.selectOptions(target, "EDU");
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "education matter");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest Department" }));
    await waitFor(() =>
      expect(posted(api, `${BASE}/suggest`)).toEqual([
        { office_code: "EDU", reason: "education matter", from_office_code: "HEALTH" },
      ]),
    );
  });

  it("suggest with no department of the caller (the central operator) sends none", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ suggest: true, suggest_departments: [] }), { primary: null })),
      "GET /custody/recipients": DEPTS,
      [`POST ${BASE}/suggest`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Suggest Department" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest Another Department" });
    expect(within(dialog).queryByLabelText("Suggest From")).toBeNull();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "FIN — Finance" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "FIN");
    await userEvent.type(within(dialog).getByLabelText("Reason (Required)"), "theirs");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest Department" }));
    await waitFor(() => expect(posted(api, `${BASE}/suggest`)).toEqual([{ office_code: "FIN", reason: "theirs" }]));
  });

  it("assign (allot) with two departments shows the chosen department's unit and officer and sends its code", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), twoRows(actions({ allot: true, allot_departments: ["EDU", "HEALTH"] }))),
      "GET /custody/recipients": (call: { url: string }) =>
        call.url.includes("department=HEALTH")
          ? { departments: [], units: [], total: 1, items: [{ user_id: "u-10", full_name: "New Officer", designation: null, office_code: "HEALTH" }] }
          : DEPTS,
      [`POST ${BASE}/allot`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = screen.getByRole("dialog", { name: "Assign This Case" });
    expect(within(dialog).queryByLabelText("Dealing Officer")).toBeNull(); // nothing until the department is chosen
    await userEvent.selectOptions(within(dialog).getByLabelText("For"), "EDU");
    expect(within(dialog).getByRole("option", { name: "Keep As Is (EDU-DSE)" })).toBeInTheDocument();
    expect(within(dialog).getByRole("option", { name: "Keep As Is (Officer Two)" })).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("For"), "HEALTH");
    expect(within(dialog).getByRole("option", { name: "Keep As Is (Health Officer)" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("option", { name: "Keep As Is (Officer Two)" })).toBeNull();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "New Officer, HEALTH" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Dealing Officer"), "u-10");
    await userEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(posted(api, `${BASE}/allot`)).toEqual([{ office_code: "HEALTH", officer_user_id: "u-10" }]));
  });

  it("AllotDialog wording: Assign This Case, Keep As Is, Whole Department and No Dealing Officer (claim-assign-wording, decision 3)", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ allot: true, allot_departments: ["EDU"] }))),
      "GET /custody/recipients": { departments: [], units: [{ code: "EDU-DSE", name: "Secondary Education" }], total: 0, items: [] },
      [`POST ${BASE}/allot`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = screen.getByRole("dialog", { name: "Assign This Case" });
    expect(within(dialog).getByText(/Choose who in the department handles this case\./)).toBeInTheDocument();
    const unit = within(dialog).getByLabelText("Responsible Unit");
    const officer = within(dialog).getByLabelText("Dealing Officer");
    expect(unit.closest(".row")).toBe(officer.closest(".row"));
    expect(within(unit).getAllByRole("option").map((o) => o.textContent).slice(0, 2)).toEqual(["Keep As Is (EDU-DSE)", "Whole Department"]);
    expect(within(officer).getAllByRole("option").map((o) => o.textContent).slice(0, 2)).toEqual(["Keep As Is (Officer Two)", "No Dealing Officer"]);
    expect(within(dialog).getByRole("button", { name: "Assign" })).toBeDisabled(); // both Keep As Is
    await userEvent.selectOptions(unit, within(unit).getByRole("option", { name: "Whole Department" }));
    await userEvent.selectOptions(officer, within(officer).getByRole("option", { name: "No Dealing Officer" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() =>
      expect(posted(api, `${BASE}/allot`)).toEqual([{ office_code: "EDU", unit_code: null, officer_user_id: null }]),
    );
  });

  it("take over with two departments sends the chosen code and that row's officer", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), twoRows(actions({ take_over: true, take_over_departments: ["EDU", "HEALTH"] }))),
      [`POST ${BASE}/take-over`]: {},
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Take Over" }));
    const dialog = screen.getByRole("dialog", { name: "Take Over This Case" });
    expect(within(dialog).queryByText(/is the dealing officer/)).toBeNull();
    await userEvent.selectOptions(within(dialog).getByLabelText("For"), "HEALTH");
    expect(within(dialog).getByText(/Health Officer is the dealing officer/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Take Over" }));
    await waitFor(() =>
      expect(posted(api, `${BASE}/take-over`)).toEqual([{ office_code: "HEALTH", expected_officer_user_id: "u-9" }]),
    );
  });

  it("no Assign or Take over button without a department list", async () => {
    browserApi(overviewRoutes(detail(), ownership(actions({ request_transfer: true, transfer_from: "EDU" }))));
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    const card = await screen.findByRole("region", { name: "Ownership" });
    await within(card).findByRole("button", { name: "Request Transfer" });
    expect(within(card).queryByRole("button", { name: "Assign" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Take Over" })).toBeNull();
  });

  it("the super admin's claim with a list offers only those departments", async () => {
    const api = browserApi({
      ...overviewRoutes(detail(), ownership(actions({ claim: true, claim_departments: ["HEALTH", "REV"] }))),
      "GET /custody/recipients": DEPTS,
      [`POST ${BASE}/claim`]: json(201, {}),
    });
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim This Case" });
    const pick = within(dialog).getByLabelText("Claim For");
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a Department", "HEALTH", "REV"]);
    await userEvent.selectOptions(pick, "REV");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() => expect(posted(api, `${BASE}/claim`)).toEqual([{ office_code: "REV" }]));
    expect(api.calls.some((c) => c.path === "/custody/recipients")).toBe(false);
  });
});

describe("documents paging and inline viewing (portal-cases-followups)", () => {
  const doc = (id: string, group: string, extra: Partial<DocumentItem> = {}): DocumentItem =>
    ({
      id,
      doc_group: group,
      doc_type: "affidavit",
      doc_type_label: "Affidavit",
      doc_date: "2026-09-01",
      description: `${id} description`,
      original_filename: `${id}.pdf`,
      mime: "application/pdf",
      size_bytes: 2048,
      page_count: 1,
      uploaded_by: null,
      office: null,
      visibility: "case_scope",
      assistant_available: false,
      sourcetrace_status: "not_applicable",
      text_status: "extracted",
      archived_at: null,
      ...extra,
    }) as DocumentItem;

  it("the text line is in plain words: scanned, old Word, searchable; never the raw value (document-ocr)", async () => {
    const filings = [
      doc("f-pdf", "court_filing", { text_status: "none", mime: "application/pdf" }),
      doc("f-png", "court_filing", { text_status: "none", mime: "image/png" }),
      doc("f-doc", "court_filing", { text_status: "none", mime: "application/msword" }),
      doc("f-ok", "court_filing", { text_status: "extracted" }),
      doc("f-wait", "court_filing", { text_status: "pending" }),
      doc("f-bad", "court_filing", { text_status: "failed" }),
    ];
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/documents`]: (call: { url: string }) => {
        const g = new URL(call.url, "http://x").searchParams.get("group");
        return g === "court_filing" ? { items: filings, total: filings.length } : { items: [], total: 0 };
      },
    });
    renderWithClient(<Documents caseRef={REF} />);
    const region = await screen.findByRole("region", { name: "Court Filings" });
    const row = (id: string) => within(region).getByText(`${id} description`).closest("tr")! as HTMLElement;
    expect(within(row("f-pdf")).getByText("Text: Scanned, Not Read")).toBeInTheDocument();
    expect(within(row("f-png")).getByText("Text: Scanned, Not Read")).toBeInTheDocument();
    expect(within(row("f-doc")).getByText("Text: Old Word Format, Not Read")).toBeInTheDocument();
    expect(within(row("f-ok")).getByText("Text: Searchable")).toBeInTheDocument();
    expect(within(row("f-wait")).getByText("Text: Being Read")).toBeInTheDocument();
    expect(within(row("f-bad")).getByText("Text: Text Could Not Be Read")).toBeInTheDocument();
    expect(within(region).queryByText(/\bnone\b/)).toBeNull();
  });

  it("each group is its own query with its own pager; empty groups are hidden", async () => {
    const records = Array.from({ length: 51 }, (_, i) => doc(`r-${i}`, "court_record"));
    const api = browserApi({
      "GET /me": me(),
      [`GET ${BASE}/documents`]: (call: { url: string }) => {
        const q = new URL(call.url, "http://x").searchParams;
        const g = q.get("group");
        const offset = Number(q.get("offset") ?? 0);
        const limit = Number(q.get("limit") ?? 50);
        if (g === "court_record") return { items: records.slice(offset, offset + limit), total: records.length };
        if (g === "internal") return { items: [doc("i-1", "internal")], total: 1 };
        return { items: [], total: 0 };
      },
    });
    renderWithClient(<Documents caseRef={REF} />);
    const orders = await screen.findByRole("region", { name: "Court Orders" });
    expect(within(orders).getByText("51 in this group")).toBeInTheDocument();
    expect(within(orders).getByText("1–50 of 51")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Internal Documents" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Court Filings" })).toBeNull();
    const groups = api.calls.filter((c) => c.path.startsWith(`${BASE}/documents`)).map((c) => new URL(c.url, "http://x").searchParams.get("group"));
    expect(new Set(groups)).toEqual(new Set(["court_record", "court_filing", "internal"]));
    expect(api.calls.every((c) => !c.url.includes("limit=200"))).toBe(true);
    await userEvent.click(within(orders).getByRole("button", { name: "Next" }));
    expect(await within(orders).findByText("51–51 of 51")).toBeInTheDocument();
    expect(api.calls.some((c) => c.url.includes("group=court_record") && c.url.includes("offset=50"))).toBe(true);
  });

  it("says No documents when all three groups are empty", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}/documents`]: { items: [], total: 0 } });
    renderWithClient(<Documents caseRef={REF} />);
    expect(await screen.findByText("No documents.")).toBeInTheDocument();
  });

  it("note attachments: Word downloads only, a PDF and an image can be viewed", async () => {
    const att = (id: string, mime: string) => ({ id, ref_no: null, doc_type: "other", original_filename: `${id}`, mime, size_bytes: 10 });
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/notes`]: {
        items: [
          {
            id: "n-1",
            ref_no: "ASLMS/EDU/NOTE/2026/000001",
            seq_no: 1,
            kind: "remark",
            kind_label: "Remark",
            body: "with files",
            author: { name: "Edu Admin", designation: null, office_code: "EDU", role: "dept_admin" },
            created_at: "2026-10-01T10:00:00Z",
            visibility: "case_scope",
            attachments: [
              att("a-word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
              att("a-pdf", "application/pdf"),
              att("a-img", "image/png"),
            ],
            supersedes: null,
            superseded_by: null,
            custody_leg_seq_no: null,
            drafted_at: null,
          } as unknown as Note,
        ],
        total: 1,
      },
    });
    renderWithClient(<Notes caseRef={REF} />);
    const item = (name: string) => screen.getByText(name, { exact: false }).closest("li")!;
    await screen.findByText("with files");
    expect(await within(item("a-word")).findByRole("link", { name: "Download" })).toBeInTheDocument();
    expect(within(item("a-word")).queryByRole("link", { name: "View" })).toBeNull();
    expect(within(item("a-pdf")).getByRole("link", { name: "View" })).toHaveAttribute("href", "/api/backend/documents/a-pdf/file?disposition=inline");
    expect(within(item("a-img")).getByRole("link", { name: "View" })).toBeInTheDocument();
  });
});

describe("the Hearings tab (portal-causelist, decision 12)", () => {
  it("each listing links to that day's cause list for its bench (date only without a bench id)", async () => {
    const listing = {
      list_type: "daily",
      bench_label: "HONOURABLE THE CHIEF JUSTICE",
      court_no: "10",
      sr_no: 4,
      printed_sr: "4",
      section: "ORDERS",
      is_connected: false,
      counsel_codes: [],
      remarks: null,
      source: "pdf_parse",
    };
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/hearings`]: { items: [], total: 0 },
      [`GET ${BASE}/listings`]: {
        items: [
          { ...listing, list_date: "2026-10-13", bench_id: 1854 },
          { ...listing, list_date: "2026-10-20", bench_id: null, bench_label: null },
        ],
        total: 2,
      },
    });
    renderWithClient(<Hearings caseRef={REF} />);
    const links = await screen.findAllByRole("link", { name: "Open the Cause List" });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/causelist?date=2026-10-13&bench_id=1854",
      "/causelist?date=2026-10-20",
    ]);
  });

  it("a row of a replaced list is greyed out and says so (court-data-freshness, decision 17)", async () => {
    const listing = {
      list_type: "daily",
      bench_label: "HONOURABLE THE CHIEF JUSTICE",
      court_no: "10",
      sr_no: 4,
      printed_sr: "4",
      section: "ORDERS",
      is_connected: false,
      counsel_codes: [],
      remarks: null,
      source: "pdf_parse",
      list_date: "2026-10-13",
      bench_id: 1854,
    };
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/hearings`]: { items: [], total: 0 },
      [`GET ${BASE}/listings`]: {
        items: [
          { ...listing, court_no: "11", superseded: false, list_version: 2 },
          { ...listing, superseded: true, list_version: 1 },
        ],
        total: 2,
      },
    });
    renderWithClient(<Hearings caseRef={REF} />);
    const label = await screen.findByText("Replaced by a Corrected List");
    expect(screen.getAllByText("Replaced by a Corrected List")).toHaveLength(1);
    expect(label.closest("tr") ?? label.closest("li") ?? label.parentElement).toBeTruthy();
  });
});

describe("the Audit trail link (portal-audit-health, decision 7)", () => {
  function auditMe(role: "auditor" | "dept_admin", functions: Permission[]) {
    return makeMe(functions, role, {
      memberships: [
        {
          id: "m-1",
          office: { code: "GOA", name: "Government of Assam", kind: "department" },
          department_code: role === "auditor" ? null : "EDU",
          designation: null,
          role,
          is_primary: true,
          is_active: true,
          functions,
        },
      ],
    });
  }

  it("shows for an audit reader with the case's reference", async () => {
    browserApi({ "GET /me": auditMe("auditor", ["audit.view", "cases.view_all", ...READ]), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    // portal-ui-redesign, decision 24: in the header's "More actions" menu
    await userEvent.click(await screen.findByRole("button", { name: "More Actions" }));
    expect(await screen.findByRole("menuitem", { name: "Audit Trail" })).toHaveAttribute(
      "href",
      "/audit?case=ASLMS%2FGHC%2FCASE%2F2026%2F000001",
    );
  });

  it("does not show without readsAudit", async () => {
    browserApi({ "GET /me": auditMe("dept_admin", ["audit.view", ...READ]), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    await screen.findByRole("navigation", { name: "Case Sections" });
    const more = screen.queryByRole("button", { name: "More Actions" });
    if (more) await userEvent.click(more);
    expect(screen.queryByRole("menuitem", { name: "Audit Trail" })).toBeNull();
  });
});

describe("next dates from orders on the case page (portal-next-dates, decisions 8, 10, 11)", () => {
  const ORDER = { id: "o-4", order_no: "4", order_date: "2026-10-12", document_id: "d-4", phrase: "List on 20.11.2026.", rule: "list_on_date" };
  function nd(extra: Partial<NonNullable<CaseDetail["next_date_from_orders"]>> = {}) {
    return {
      id: "nd-1",
      ref_no: null,
      next_date: "2026-11-20",
      source: "order_specific",
      confidence: 0.95,
      needs_review: false,
      review_status: "not_needed",
      order: ORDER,
      note: null,
      reviewed_by: null,
      reviewed_at: null,
      created_by: null,
      created_at: "2026-10-12T10:00:00Z",
      ...extra,
    };
  }
  const REVIEW_ITEM = {
    kind: "confirm",
    id: "nd-2",
    case: { id: "c-1", ref_no: "ASLMS/GHC/CASE/2026/000001", cnr: "ASHC010012342026", case_no_text: "WP(C)/1234/2026" },
    order: { id: "o-5", order_no: "5", order_date: "2026-10-14", document_id: null },
    phrase: "List after two weeks.",
    rule: "list_after_period",
    next_date: "2026-10-28",
    act_by: "2026-10-22",
    alert_ref_no: null,
    departments: ["EDU"],
  };

  async function card(c: CaseDetail, extra: Record<string, unknown> = {}) {
    const api = browserApi({ ...overviewRoutes(c, ownership(actions())), ...extra });
    const view = renderWithClient(<Overview caseRef={REF} />);
    const region = await screen.findByRole("region", { name: "Next Date From Orders" });
    return { api, region, ...view };
  }

  it("shows a fixed, a confirmed and an entered date, and says when there is none", async () => {
    let r = await card(detail({ next_date_from_orders: nd() }));
    expect(within(r.region).getByText("20 Nov 2026")).toBeInTheDocument();
    expect(within(r.region).getByText("Fixed in the order of 12 Oct 2026")).toBeInTheDocument();
    expect(within(r.region).getByText("What the Order Says")).toBeInTheDocument();
    expect(within(r.region).getByText("“List on 20.11.2026.”")).toBeInTheDocument();
    expect(within(r.region).getByRole("link", { name: "All Next Dates" })).toHaveAttribute("href", `${BASE}/hearings#next-dates`);
    r.unmount();
    r = await card(
      detail({
        next_date_from_orders: nd({
          source: "order_period",
          review_status: "confirmed",
          reviewed_by: { name: "Edu Admin" },
          reviewed_at: "2026-10-14T05:00:00Z",
        }),
      }),
    );
    expect(within(r.region).getByText("Counted from the order of 12 Oct 2026 · confirmed by Edu Admin on 14 Oct 2026")).toBeInTheDocument();
    r.unmount();
    r = await card(
      detail({
        next_date_from_orders: nd({
          source: "manual",
          ref_no: "ASLMS-EDU-NXT-2026-000001",
          order: null,
          note: "Fixed by the court orally",
          created_by: { name: "Officer One" },
          created_at: "2026-10-15T05:00:00Z",
        }),
      }),
    );
    expect(within(r.region).getByText("Entered by Officer One on 15 Oct 2026")).toBeInTheDocument();
    expect(within(r.region).getByText(/Fixed by the court orally/)).toBeInTheDocument();
    r.unmount();
    r = await card(detail({ next_date_from_orders: null }));
    expect(within(r.region).getByText("No next date from the orders yet.")).toBeInTheDocument();
  });

  it("Waiting for you asks the queue for this case only when it has items; Enter next date only by the flag", async () => {
    let r = await card(detail({ next_dates_to_review: 0 }));
    expect(r.api.calls.some((c) => c.path.startsWith("/next-dates/review"))).toBe(false);
    expect(within(r.region).queryByRole("group", { name: "Waiting for You" })).toBeNull();
    expect(within(r.region).queryByRole("button", { name: "Enter Next Date" })).toBeNull();
    r.unmount();
    r = await card(
      detail({ next_dates_to_review: 1, workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: true } }),
      { "GET /next-dates/review": { items: [REVIEW_ITEM], total: 1 } },
    );
    const panel = await within(r.region).findByRole("group", { name: "Waiting for You" });
    await within(panel).findByRole("button", { name: "Confirm next date of WP(C)/1234/2026" });
    const call = r.api.calls.find((c) => c.path.startsWith("/next-dates/review"))!;
    expect(new URLSearchParams(call.path.split("?")[1]).get("q")).toBe("c-1");
    expect(within(panel).queryByRole("columnheader", { name: "Case" })).toBeNull();
    expect(within(r.region).getByRole("button", { name: "Enter Next Date" })).toBeInTheDocument();
  });

  it("Enter next date from the case page posts no order", async () => {
    const { api, region } = await card(
      detail({ workflow: { note_mode: "permanent", upload: true, set_stage: true, next_dates: true } }),
      { [`POST ${BASE}/next-dates`]: json(201, nd({ source: "manual", next_date: "2026-12-01" })) },
    );
    await userEvent.click(within(region).getByRole("button", { name: "Enter Next Date" }));
    const dialog = screen.getByRole("dialog");
    const day = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
    await userEvent.type(within(dialog).getByLabelText("Next Date"), day);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ next_date: day });
    expect(await within(region).findByText("Saved. 1 Dec 2026 is the next date of WP(C)/1234/2026.")).toBeInTheDocument();
  });

  it("the Latest order card carries the order's reading", async () => {
    const order = {
      id: "o-4",
      order_no: "4",
      order_date: "2026-10-12",
      kind: "interim",
      order_judge_name: null,
      download_status: "stored",
      document_id: "d-4",
      order_details: null,
      is_reportable: null,
      date_judgement_pronounced: null,
      date_judgement_reserved: null,
      next_date_status: "specific",
      next_date_found: "2026-11-20",
      next_date_rule: "list_on_date",
      next_date_phrase: "List on 20.11.2026.",
    };
    browserApi({ ...overviewRoutes(detail(), ownership(actions())), [`GET ${BASE}/orders`]: { items: [order], total: 1 } });
    renderWithClient(<Overview caseRef={REF} />);
    const latest = await screen.findByRole("region", { name: "Latest Order" });
    expect(await within(latest).findByText("Next date found in the order: 20 Nov 2026")).toBeInTheDocument();
  });

  it("the Orders tab reads each order in plain words, never the rule code", async () => {
    const base = {
      kind: "interim",
      order_judge_name: null,
      download_status: "pending",
      document_id: null,
      order_details: null,
      is_reportable: null,
      date_judgement_pronounced: null,
      date_judgement_reserved: null,
      next_date_found: null,
      next_date_rule: null,
      next_date_phrase: null,
    };
    const statuses: [string, Record<string, unknown>][] = [
      ["specific", { next_date_found: "2026-11-20", next_date_rule: "list_on_date", next_date_phrase: "List on 20.11.2026." }],
      ["period", { next_date_found: "2026-10-26", next_date_rule: "list_after_period", next_date_phrase: "List after two weeks." }],
      ["unclear", { next_date_rule: "conflicting_dates", next_date_phrase: "List with WP(C)/9/2026." }],
      ["none", {}],
      ["no_text", {}],
      ["pending", {}],
    ];
    browserApi({
      "GET /me": me(["cases.view_scope"]),
      [`GET ${BASE}/orders`]: {
        items: statuses.map(([status, extra], i) => ({
          ...base,
          id: `o-${i}`,
          order_no: String(i + 1),
          order_date: "2026-10-12",
          next_date_status: status,
          ...extra,
        })),
        total: statuses.length,
      },
    });
    renderWithClient(<Orders caseRef={REF} />);
    expect((await screen.findAllByText("Next Date Read:")).length).toBe(statuses.length);
    expect(screen.getByText("20 Nov 2026")).toBeInTheDocument();
    expect(screen.getByText("Date in the Order")).toBeInTheDocument();
    expect(screen.getByText("26 Oct 2026")).toBeInTheDocument();
    expect(screen.getByText("counted from the order")).toBeInTheDocument();
    expect(screen.getByText("No Clear Date")).toBeInTheDocument();
    expect(screen.getByText("No next date given")).toBeInTheDocument();
    expect(screen.getByText("Could not be read (scanned copy)")).toBeInTheDocument();
    expect(screen.getByText("Not Read Yet")).toBeInTheDocument();
    expect(screen.getAllByText("What the Order Says")).toHaveLength(3);
    expect(screen.getByText("“List after two weeks.”")).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/list_on_date|list_after_period|conflicting_dates/);
  });

  it("the Hearings tab lists every next date with the one used for the calendar and the NXT reference", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/hearings`]: { items: [], total: 0 },
      [`GET ${BASE}/listings`]: { items: [], total: 0 },
      [`GET ${BASE}/next-dates`]: {
        items: [
          {
            ...nd({
              id: "nd-9",
              source: "manual",
              ref_no: "ASLMS-EDU-NXT-2026-000001",
              order: null,
              next_date: "2026-12-01",
              note: "Fixed orally",
              created_by: { name: "Officer One" },
              created_at: "2026-10-15T05:00:00Z",
            }),
            effective: true,
          },
          { ...nd({ id: "nd-8", source: "order_period", review_status: "superseded" }), effective: false },
          { ...nd({ id: "nd-7", source: "order_period", review_status: "pending" }), effective: false },
        ],
        total: 3,
      },
    });
    renderWithClient(<Hearings caseRef={REF} />);
    const section = await screen.findByRole("region", { name: "Next Dates" });
    expect(section).toHaveAttribute("id", "next-dates");
    const table = await within(section).findByRole("table", { name: "Next Dates" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Used for the Calendar")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("ASLMS-EDU-NXT-2026-000001")).toHaveClass("mono");
    expect(within(rows[0]!).getByText("Entered by Hand")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Officer One, 15 Oct 2026")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Fixed orally")).toBeInTheDocument();
    expect(within(rows[1]!).queryByText("Used for the Calendar")).toBeNull();
    expect(within(rows[1]!).getByText("Replaced by a Later Date")).toBeInTheDocument();
    // a reader without the action (workflow.next_dates false) sees the neutral wording
    expect(within(rows[2]!).getByText("Waiting for Confirmation")).toBeInTheDocument();
  });
});

describe("the Timeline tab (portal-ui-redesign, decision 15)", () => {
  it("each row leads with its date in the fixed date column", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/timeline`]: {
        items: [
          { type: "custody_moved", label: "File sent", occurred_at: "2026-10-12T05:00:00Z", actor_name: "Edu Admin", payload: {} },
          { type: "case_claimed", label: "Claimed", occurred_at: "2026-10-01T05:00:00Z", actor_name: null, payload: {} },
        ],
        total: 2,
      },
    });
    renderWithClient(<Timeline caseRef={REF} />);
    const list = await screen.findByRole("list", { name: "Timeline" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row.firstElementChild).toHaveAttribute("data-lead", "date");
    expect(within(rows[0]!).getByText("File sent")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("12")).toBeInTheDocument();
  });
});

describe("round 1 and round 3 advisories (design portal-ui-polish, decisions 2, 11 and 12)", () => {
  it("header h1 is monospace for a bare ref_no", async () => {
    const bare = detail({ identity: { ...detail().identity, case_no_text: null } });
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: bare });
    const { unmount } = renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const h1 = await screen.findByRole("heading", { level: 1, name: "ASLMS/GHC/CASE/2026/000001" });
    expect(h1).toHaveClass("mono");
    expect(h1).not.toHaveClass("cno");
    unmount();
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const numbered = await screen.findByRole("heading", { level: 1, name: "WP(C)/1234/2026" });
    expect(numbered).toHaveClass("cno");
    expect(numbered).not.toHaveClass("mono");
  });

  it("header next hearing shows printed_sr", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/listings`]: {
        items: [{ list_date: "2026-11-20", court_no: "3", sr_no: 14, printed_sr: "14A", list_type: "daily", source: "causelist" }],
        total: 1,
      },
    });
    renderWithClient(<CaseFrame caseRef={REF}>body</CaseFrame>);
    const header = await screen.findByRole("region", { name: "Case Summary" });
    const fact = () => within(header).getByText("Next Hearing", { selector: "dt" }).nextElementSibling as HTMLElement;
    await waitFor(() => expect(fact()).toHaveTextContent(/20 Nov 2026.* · Court 3, item 14A/));
  });

  it("custody tab has one primary", async () => {
    resetNav(`${BASE}/custody`);
    const d = detail();
    browserApi({
      ...overviewRoutes(d, ownership(actions())),
      "GET /workflow/codes": { note_kinds: [], pending_actions: [], stages: [], response_modes: [], custody_reasons: [], limits: { note_max_chars: 200, attachments_max_files: 2, note_drafts_max: 20 } },
      [`GET ${BASE}/custody`]: { card: d.custody, legs: [], total: 0 },
      [`GET ${BASE}/stages`]: { current: null, history: [], gaps: [] },
    });
    const { container } = renderWithClient(
      <CaseFrame caseRef={REF}>
        <CustodyTab caseRef={REF} />
      </CaseFrame>,
    );
    const card = await screen.findByRole("region", { name: "Journey" });
    const send = await within(card).findByRole("button", { name: "Send Case" });
    expect(send).toHaveAttribute("data-variant", "secondary");
    await screen.findByRole("region", { name: "Case Summary" });
    expect(container.querySelectorAll(PRIMARY_SELECTOR).length).toBe(1);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("Details renders a DataTable with a primary cell", async () => {
    browserApi({ "GET /me": me(), [`GET ${BASE}`]: detail() });
    renderWithClient(<Details caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Acts and Sections" }));
    expectDataTable(screen.getByRole("table", { name: "Objections" }));
  });

  it("Documents renders a DataTable with a primary cell", async () => {
    const doc = {
      id: "d-1",
      doc_group: "court_record",
      doc_type: "order",
      doc_type_label: "Order",
      doc_date: "2026-09-01",
      description: "Order of 1 September",
      original_filename: "d-1.pdf",
      mime: "application/pdf",
      size_bytes: 2048,
      page_count: 3,
      uploaded_by: null,
      office: null,
      visibility: "case_scope",
      assistant_available: true,
      sourcetrace_status: "ingested",
      text_status: "extracted",
      archived_at: null,
    } as unknown as DocumentItem;
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/documents`]: (call: { url: string }) =>
        new URL(call.url, "http://x").searchParams.get("group") === "court_record" ? { items: [doc], total: 1 } : { items: [], total: 0 },
    });
    renderWithClient(<Documents caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Court Orders" }));
  });

  it("Hearings renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/hearings`]: {
        items: [{ business_date: "2026-09-25", hearing_date: "2026-09-25", purpose: "For orders", bench_text: "Single Bench", judge_designation: null, next_date: "2026-11-20", business_text: "Heard", short_order_text: null }],
        total: 1,
      },
      [`GET ${BASE}/listings`]: {
        items: [{ list_date: "2026-11-20", list_type: "daily", bench_id: 1854, bench_label: "Court 3", court_no: "3", sr_no: 14, printed_sr: "14A", section: null, is_connected: false, counsel_codes: ["SC,EDU"], remarks: null, source: "pdf_parse" }],
        total: 1,
      },
    });
    renderWithClient(<Hearings caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Hearings" }));
    expectDataTable(await screen.findByRole("table", { name: "Cause-list Appearances" }));
  });

  it("Links renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/links`]: {
        items: [{ direction: "out", kind: "appeal", case: null, case_no_text: "WA/2/2026", cnr: null, filing_number_text: null, source: "dossier", visible: false }],
      },
      [`GET ${BASE}/links/graph`]: { nodes: [], edges: [], truncated: false },
    });
    renderWithClient(<Links caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Linked Cases" }));
  });

  it("Parties renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}/parties`]: {
        parties: [{ name: "RAM KUMAR", party_no: 1, role: "petitioner", address: null, has_legal_heir: null, is_current: true }],
        advocates: [{ name_as_listed: "A. Das", side: "petitioner", counsel_code: null, bar_reg_no: null, is_current: true }],
      },
    });
    renderWithClient(<Parties caseRef={REF} />);
    expectDataTable(await screen.findByRole("table", { name: "Parties" }));
    expectDataTable(screen.getByRole("table", { name: "Advocates" }));
  });
});

describe("the next dates list is a DataTable (design portal-ui-polish, decision 15)", () => {
  it("CaseNextDate renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": me(),
      [`GET ${BASE}`]: detail(),
      [`GET ${BASE}/hearings`]: { items: [], total: 0 },
      [`GET ${BASE}/listings`]: { items: [], total: 0 },
      [`GET ${BASE}/next-dates`]: {
        items: [
          {
            id: "nd-9",
            ref_no: "ASLMS-EDU-NXT-2026-000001",
            next_date: "2026-12-01",
            source: "manual",
            confidence: null,
            needs_review: false,
            review_status: "not_needed",
            order: null,
            note: "Fixed orally",
            reviewed_by: null,
            reviewed_at: null,
            created_by: { name: "Officer One" },
            created_at: "2026-10-15T05:00:00Z",
            effective: true,
          },
        ],
        total: 1,
      },
    });
    renderWithClient(<Hearings caseRef={REF} />);
    const section = await screen.findByRole("region", { name: "Next Dates" });
    expectDataTable(await within(section).findByRole("table", { name: "Next Dates" }));
  });
});

describe("recommendation statuses in words (ownership-refinements)", () => {
  it("another department's closed recommendation reads as claimed by another department", async () => {
    const closed = {
      id: "r-9",
      case: {} as CaseOwnershipView["recommendations"][number]["case"],
      office_code: "HEALTH",
      score: 0.6,
      band: "medium",
      status: "claimed_elsewhere",
      origin: "cause_list",
      reason: "claimed by EDU",
      signals: [],
      acted_at: "2026-10-21T10:00:00Z",
      created_at: "2026-10-20T10:00:00Z",
      current_owner_code: "EDU",
      suggested_by_office_code: null,
    } as CaseOwnershipView["recommendations"][number];
    browserApi(overviewRoutes(detail(), ownership(actions(), { recommendations: [closed] })));
    renderWithClient(<Overview caseRef={REF} />);
    await openOwnership();
    const card = await screen.findByRole("region", { name: "Ownership" });
    expect(await within(card).findByText("Closed: Claimed by Another Department")).toBeInTheDocument();
    expect(within(card).queryByText("claimed_elsewhere")).toBeNull();
  });
});

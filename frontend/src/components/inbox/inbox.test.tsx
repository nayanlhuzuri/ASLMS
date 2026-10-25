/**
 * The Case inbox = the user's own work (design portal-ui-redesign, decisions 5 and 10.4; round 2, row 102; design
 * case-inbox-merge: the Cases list folded in): the six tabs per login with their counts, Working on (the lead badge,
 * Show, Overdue only and the side panel with the remark), the own-work rows of Claimed by me and Disposed, Department
 * cases with the full filter bar (Not allotted sends `unallotted=true`), and the old addresses. Recommended, the pool
 * and Transfers are tested with Case claim (`components/claim/claim.test.tsx`); the held and sent lists in
 * `components/files/cases-list.test.tsx`.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CustodyBrief, CustodySummary, Me, Ownership, Permission } from "@/lib/api/types";
import { setFlash } from "@/lib/flash";
import { addDays, istDay } from "@/lib/format";
import { OLD_CASES_REDIRECTS, OLD_FILES_REDIRECTS, OLD_INBOX_REDIRECTS } from "@/lib/routes";
import { admin, block, membership, myCase, officer, summary } from "@/test/claimFixtures";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { InboxFrame, InboxIndex } from "./InboxFrame";
import { ClaimedRedirect, Redirect, redirectTarget } from "./Redirects";

const COUNTS = { working: 5, files: 2, claimed: 7, disposed: 1 };

const PEOPLE = {
  departments: [],
  items: [
    { membership_id: "mm-1", user_id: "u-7", full_name: "Officer One", designation: "SO", office_code: "EDU", office_name: "Education", role_label: "Officer" },
  ],
  units: [{ code: "EDU-DSE", name: "Secondary Education" }],
  total: 1,
};

const WORKFLOW_CODES = {
  note_kinds: [],
  pending_actions: [],
  stages: [
    { code: "counsel_briefed", label: "Counsel briefed", phase: "main", sort_order: 4 },
    { code: "affidavit_filed", label: "Affidavit filed", phase: "main", sort_order: 7 },
  ],
  response_modes: [],
  custody_reasons: [],
  limits: { note_max_chars: 4000, attachments_max_files: 5, note_drafts_max: 10 },
};

function ownership(n: number, extra: Partial<Ownership> = {}): Ownership {
  return {
    id: `o-${n}`,
    case: summary(n),
    office_code: "EDU",
    role: "primary",
    status: "active",
    unit: { code: "EDU-DSE", name: "Secondary Education" },
    officer: { id: "u-7", full_name: "Officer One" },
    claimed_at: "2026-10-01T10:00:00Z",
    allotted_at: null,
    released_at: null,
    release_reason: null,
    stage: { stage: "affidavit_filed", label: "Affidavit filed", phase: "main" },
    custody: {
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { full_name: "Health Officer", designation: "Deputy Secretary" },
      with_me: false,
      pending_action: "parawise_comments",
      pending_action_label: "Parawise comments",
      since: "2026-10-01T10:00:00Z",
      due_date: null,
      overdue: false,
      overdue_days: 0,
      due_soon: false,
      sent_by: null,
    },
    ...extra,
  };
}

/** A custody brief; `with_me` by default. */
function brief(extra: Partial<CustodyBrief> = {}): CustodyBrief {
  return {
    holder_office: { code: "EDU", name: "Education" },
    holder_user: { full_name: "Anita Sharma", designation: "Under Secretary" },
    with_me: true,
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    since: "2026-10-01T10:00:00Z",
    due_date: "2026-10-10",
    overdue: true,
    overdue_days: 3,
    due_soon: false,
    sent_by: { name: "Edu Admin", designation: "Joint Secretary", office_code: "EDU" },
    ...extra,
  };
}

const SUMMARY: CustodySummary = {
  departments: [
    { code: "EDU", held: 5, due_soon: 2, overdue: 1, by_holder_department: [], by_holder: [] },
    { code: "FIN", held: 2, due_soon: 0, overdue: 0, by_holder_department: [], by_holder: [] },
  ],
};

const HEAD_FNS: Permission[] = ["cases.view_scope", "cases.claim", "cases.allot", "cases.transfer_decide", "custody.track"];

/** A department head: whole department (from `/inbox/counts`), `cases.claim` and `custody.track`. */
function head(): Me {
  return admin(HEAD_FNS, { memberships: [membership("EDU", HEAD_FNS)] });
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /me": admin(),
    "GET /inbox/counts": { departments: [block("EDU")] },
    "GET /inbox/mine/counts": COUNTS,
    "GET /inbox/mine": { items: [], total: 0 },
    "GET /inbox/claimed": { items: [ownership(1)], total: 1 },
    "GET /custody/recipients": PEOPLE,
    "GET /workflow/codes": WORKFLOW_CODES,
    "GET /custody/summary": SUMMARY,
    "GET /custody/sent": { items: [], total: 0 },
    "GET /custody/held": { items: [], total: 0 },
    ...extra,
  };
}

const lastUrl = (calls: BrowserCall[], prefix: string) => calls.filter((c) => c.path.startsWith(prefix)).at(-1)?.path ?? "";

beforeEach(() => {
  resetNav("/inbox/working");
});

describe("tabs", () => {
  it("a department officer sees Working on, Sent by me and Disposed with counts; no Claimed by me, Department cases or Pending action", async () => {
    const api = browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": { departments: [block("EDU", { whole_department: false })] } }));
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/inbox/working", "/inbox/sent", "/inbox/disposed"]);
    expect(within(tabs).getByRole("link", { name: /Working On.*\(5\)/ })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: /Disposed.*\(1\)/ })).toBeInTheDocument();
    // Sent by me is a history, not a queue: no count
    expect(within(tabs).getByRole("link", { name: "Sent by Me" })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: /Cases with Me|Claimed by Me|Department Cases|Pending Action/ })).toBeNull();
    // no pending figure is asked for by a login that tracks no department
    expect(api.calls.some((c) => c.path.startsWith("/custody/summary"))).toBe(false);
  });

  it("an officer with cases.claim also sees Claimed by me", async () => {
    browserApi(
      routes({
        "GET /me": officer(["cases.view_scope", "cases.claim"]),
        "GET /inbox/counts": { departments: [block("EDU", { whole_department: false })] },
      }),
    );
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getByRole("link", { name: /Claimed by Me.*\(7\)/ })).toHaveAttribute("href", "/inbox/claimed-by-me");
  });

  it("a department head sees all six tabs in order; Pending action counts the held cases of /custody/summary", async () => {
    const api = browserApi(routes({ "GET /me": head() }));
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    await waitFor(() => expect(within(tabs).getByRole("link", { name: /Pending Action.*\(7\)/ })).toHaveAttribute("href", "/inbox/pending"));
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/inbox/working",
      "/inbox/sent",
      "/inbox/claimed-by-me",
      "/inbox/disposed",
      "/inbox/department",
      "/inbox/pending",
    ]);
    expect(within(tabs).getByRole("link", { name: "Department Cases" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path.startsWith("/custody/summary"))).toHaveLength(1);
  });

  it("a tab the login may not open shows the not-found text", async () => {
    resetNav("/inbox/pending");
    browserApi(routes({ "GET /me": officer() }));
    renderWithClient(<InboxFrame tab="pending" params={{}} />);
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Tracking summary/ })).toBeNull();
  });

  it("Sent by me and Pending action render the existing lists", async () => {
    resetNav("/inbox/sent");
    const api = browserApi(routes({ "GET /me": head() }));
    const { unmount } = renderWithClient(<InboxFrame tab="sent" params={{}} />);
    expect(await screen.findByText("You have not sent or recalled a case.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/custody/sent"))).toBe(true);
    unmount();
    resetNav("/inbox/pending");
    renderWithClient(<InboxFrame tab="pending" params={{}} />);
    expect(await screen.findByRole("region", { name: "Tracking summary: EDU" })).toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/custody/held") && c.path.includes("scope=owned"))).toBe(true));
  });

  it("the notice of a case sent away shows once, above the tabs", async () => {
    resetNav("/inbox/sent");
    setFlash("Case sent to Health Off. It is no longer with you.");
    browserApi(routes({ "GET /me": officer() }));
    const { unmount } = renderWithClient(<InboxFrame tab="sent" params={{}} />);
    const notice = await screen.findByText("Case sent to Health Off. It is no longer with you.");
    const tabs = screen.getByRole("navigation", { name: "Case Inbox Sections" });
    expect(notice.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sessionStorage.getItem("aslms.flash")).toBeNull();
    unmount();
    renderWithClient(<InboxFrame tab="sent" params={{}} />);
    await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(screen.queryByText(/It is no longer with you/)).toBeNull();
  });

  it("the department admin also gets Department cases (whole_department)", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getByRole("link", { name: "Department Cases" })).toHaveAttribute("href", "/inbox/department");
  });

  it("a State-wide reader gets Department cases and picks any department", async () => {
    const reader = makeMe(["cases.view_scope", "cases.view_all"], "state_oversight", { memberships: [] });
    browserApi(
      routes({
        "GET /me": reader,
        "GET /inbox/counts": (call: BrowserCall) =>
          call.url.includes("office=FIN")
            ? { departments: [block("FIN")] }
            : { departments: [block(null, { whole_department: false, claimed_active: null, claimed_disposed: null })] },
        "GET /custody/recipients": (call: BrowserCall) =>
          call.url.includes("department=")
            ? PEOPLE
            : { departments: [{ code: "EDU", name: "Education" }, { code: "FIN", name: "Finance" }], items: [], units: [], total: 2 },
      }),
    );
    resetNav("/inbox/department");
    renderWithClient(<InboxFrame tab="department" params={{ department: "FIN" }} />);
    expect(await screen.findByRole("link", { name: "Department Cases" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByLabelText("Department")).toHaveValue("FIN");
    await userEvent.selectOptions(screen.getByLabelText("Department"), "EDU");
    expect(nav.push).toHaveBeenCalledWith("/inbox/department?department=EDU");
  });
});

describe("Working on (case-inbox-merge, decisions 8 and 9)", () => {
  it("columns: lead badge, case and parties, next hearing, action needed, due by, From and the chevron; only a case with me fills them", async () => {
    const soon = addDays(istDay(), 1);
    const api = browserApi(
      routes({
        "GET /inbox/mine": {
          items: [
            myCase(1, { case: summary(1, { next_hearing_date: soon }), custody: brief(), reasons: ["allotted", "file"] }),
            myCase(2, {
              custody: brief({ with_me: false, holder_user: { full_name: "Health Officer", designation: "Deputy Secretary" }, overdue: true }),
            }),
            myCase(3),
          ],
          total: 3,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const table = await screen.findByRole("table", { name: "Working On" });
    expectDataTable(table);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Status",
      "Case and Parties",
      "Next Hearing",
      "Action Needed",
      "Due By",
      "From",
      "Case Details",
    ]);
    const row1 = screen.getByRole("row", { name: "Details of WP(C)/1/2026" });
    expect(within(row1).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-000001");
    expect(within(row1).getByText("Overdue")).toBeInTheDocument();
    expect(within(row1).getByText("48 Hours")).toBeInTheDocument();
    expect(within(row1).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(row1).getByText("10 Oct 2026")).toBeInTheDocument();
    expect(within(row1).getByText("Joint Secretary, EDU")).toHaveAttribute("title", "Edu Admin");
    // allotted to me, with someone else: no badge, "—" for action, due and From
    const row2 = screen.getByRole("row", { name: "Details of WP(C)/2/2026" });
    expect(within(row2).queryByText(/Overdue|Due Soon|New/)).toBeNull();
    expect(within(row2).queryByText("Parawise comments")).toBeNull();
    expect(within(row2).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(lastUrl(api.calls, "/inbox/mine?")).toContain("view=working");
    expect(screen.getByText("3 cases")).toBeInTheDocument();
  });

  it("a row opens Case details: the brief's facts and the remark read once from the case's custody card", async () => {
    const api = browserApi(
      routes({
        "GET /inbox/mine": { items: [myCase(1, { custody: brief() }), myCase(2)], total: 2 },
        "GET /cases/ASLMS-GOA-CASE-2026-000001/custody": {
          card: { remark: "please send parawise comments" },
          items: [],
          total: 1,
          remarks_shown: true,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/1/2026" }));
    const panel = await screen.findByRole("dialog", { name: "Case Details" });
    expect(await within(panel).findByText("please send parawise comments")).toBeInTheDocument();
    for (const label of ["With", "Action Needed", "Since", "Due By", "From"]) expect(within(panel).getByText(label)).toBeInTheDocument();
    expect(within(panel).getByText("Under Secretary, Education (you)")).toBeInTheDocument();
    const custodyCalls = api.calls.filter((c) => c.path.startsWith("/cases/ASLMS-GOA-CASE-2026-000001/custody"));
    expect(custodyCalls).toHaveLength(1);
    expect(custodyCalls[0]!.path).toContain("order=desc");
    expect(custodyCalls[0]!.path).toContain("limit=1");
    expect(within(panel).queryByRole("button", { name: /send|recall/i })).toBeNull();
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // a row with no custody row reads nothing more
    await userEvent.click(screen.getByRole("row", { name: "Details of WP(C)/2/2026" }));
    const panel2 = await screen.findByRole("dialog", { name: "Case Details" });
    expect(within(panel2).getByText("No remark.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/cases/ASLMS-GOA-CASE-2026-000002/custody"))).toBe(false);
  });

  it("Show: With me reads /custody/held?scope=me, With my offices scope=office; All reads /inbox/mine", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="working" params={{}} />);
    const show = await screen.findByRole("radiogroup", { name: "Show" });
    expect(within(show).getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(show).getByRole("radio", { name: "With Me" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?held=me");
    unmount();
    const { unmount: u2 } = renderWithClient(<InboxFrame tab="working" params={{ held: "me" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("scope=me"));
    u2();
    renderWithClient(<InboxFrame tab="working" params={{ held: "offices" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("scope=office"));
  });

  it("Overdue Only: action=overdue under All, overdue=true under With me; an incoming action=overdue reads as overdue=true", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="working" params={{ overdue: "true" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/inbox/mine?")).toContain("action=overdue"));
    expect(screen.getByLabelText("Overdue Only")).toBeChecked();
    unmount();
    const { unmount: u2 } = renderWithClient(<InboxFrame tab="working" params={{ held: "me", overdue: "true" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("overdue=true"));
    expect(lastUrl(api.calls, "/custody/held?")).not.toContain("action=");
    u2();
    // a round-2 bookmark; and an old Cases with me link's `owner` is not sent to the `mine` list
    renderWithClient(<InboxFrame tab="working" params={{ action: "overdue", owner: "EDU" }} />);
    await waitFor(() => expect(screen.getByLabelText("Overdue Only")).toBeChecked());
    const url = lastUrl(api.calls, "/inbox/mine?");
    expect(url).toContain("action=overdue");
    expect(url).not.toContain("owner=");
  });

  it("the quick chips write next=n7 and overdue=true; the filtered count reads n of m", async () => {
    const api = browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { unmount } = renderWithClient(<InboxFrame tab="working" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Hearing This Week" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?next=n7");
    await userEvent.click(screen.getByRole("button", { name: "Action Overdue" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?overdue=true");
    unmount();
    resetNav("/inbox/working");
    renderWithClient(<InboxFrame tab="working" params={{ next: "n7", overdue: "true", stage: "none" }} />);
    expect(await screen.findByText("1 of 5 cases")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hearing This Week" })).toHaveAttribute("aria-pressed", "true");
    const url = lastUrl(api.calls, "/inbox/mine?");
    for (const part of ["view=working", "action=overdue", "stage=none", `next_from=${istDay()}`]) expect(url).toContain(part);
  });

  it("Stage is on the first row; words, case type, year and court are under More filters", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="working" params={{}} />);
    const stage = await screen.findByLabelText("Stage");
    await waitFor(() => expect(within(stage).getByRole("option", { name: "Counsel briefed" })).toBeInTheDocument());
    expect(within(stage).getByRole("option", { name: "No stage set" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Year")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More Filters" }));
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Words/)).toBeInTheDocument();
    expect(screen.getByLabelText("Court")).toBeInTheDocument();
    await userEvent.selectOptions(stage, "counsel_briefed");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?stage=counsel_briefed");
  });

  it("the page has at most one primary button (decision 16)", async () => {
    browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { container } = renderWithClient(<InboxFrame tab="working" params={{}} />);
    await screen.findByRole("row", { name: "Details of WP(C)/1/2026" });
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });
});

describe("own work: Claimed by me and Disposed", () => {
  beforeEach(() => resetNav("/inbox/claimed-by-me"));

  it("rows show the case, stage, next hearing badge and my action; a row opens the case page", async () => {
    const soon = addDays(istDay(), 1);
    const api = browserApi(
      routes({
        "GET /inbox/mine": {
          items: [
            myCase(1, {
              case: summary(1, { next_hearing_date: soon }),
              stage: { stage: "counsel_briefed", label: "Counsel briefed", phase: "main" },
              custody: brief(),
              reasons: ["claimed", "file"],
            }),
            myCase(2),
          ],
          total: 2,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="claimed" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(within(row).getByText("Counsel briefed")).toBeInTheDocument();
    expect(within(row).getByText("48 Hours")).toBeInTheDocument();
    expect(within(row).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(row).getByText("Overdue 3 days")).toBeInTheDocument();
    expect(within(row).getByText("RAM KUMAR", { exact: false })).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: "Open WP(C)/2/2026" })).getByText("No stage set")).toBeInTheDocument();
    expect(lastUrl(api.calls, "/inbox/mine?")).toContain("view=claimed");
    await userEvent.click(row);
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001");
  });

  it("an empty view says when items appear", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="claimed" params={{}} />);
    expect(await screen.findByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByText(/Cases you claim for your department/)).toBeInTheDocument();
  });
});

describe("Department Cases", () => {
  beforeEach(() => resetNav("/inbox/department"));

  it("the filter grid: Search, Unit, Officer, Stage, Next hearing; More filters slides open with the rest", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(within(row).getByText("EDU-DSE")).toBeInTheDocument();
    expect(within(row).getByText("Officer One", { exact: false })).toBeInTheDocument();
    expect(within(row).getByText("Affidavit filed")).toBeInTheDocument();
    expect(within(row).getByText("Health Officer", { exact: false })).toBeInTheDocument();
    for (const label of ["Unit", "Officer", "Stage", "Next Hearing"]) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Words/)).toBeInTheDocument();
    const next = screen.getByLabelText("Next Hearing");
    expect(within(next).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any Date",
      "This Week",
      "Next 30 Days",
      "Choose Dates…",
    ]);
    expect(screen.queryByLabelText("With")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More Filters" }));
    for (const label of ["Case Type", "Year", "Court", "With", "Action"]) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Active" })).toHaveAttribute("aria-checked", "true");
  });

  it("Not allotted sends unallotted=true; the chips show with n of m and removing one applies at once", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    const officerSelect = await screen.findByLabelText("Officer");
    await waitFor(() => expect(within(officerSelect).getByRole("option", { name: "Officer One" })).toBeInTheDocument());
    await userEvent.selectOptions(officerSelect, "none");
    await userEvent.selectOptions(screen.getByLabelText("Next Hearing"), "n7");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?next=n7&officer=none");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ officer: "none", next: "n7", holder: "elsewhere", action: "overdue" }} />);
    expect(await screen.findByText("1 of 4 cases")).toBeInTheDocument();
    const url = lastUrl(api.calls, "/inbox/claimed?");
    for (const part of ["office=EDU", "case_state=active", "unallotted=true", "holder=elsewhere", "action=overdue", "next_from="]) {
      expect(url).toContain(part);
    }
    expect(url).not.toContain("officer_user_id");
    const chips = screen.getByRole("list", { name: "Applied Filters" });
    expect(within(chips).getByText("Officer: Not Allotted")).toBeInTheDocument();
    expect(within(chips).getByText("With: Another Department")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove filter Officer: Not Allotted" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?next=n7&holder=elsewhere&action=overdue");
  });

  it("an officer chosen sends officer_user_id; Disposed is the Status switch", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{ officer: "u-7" }} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("officer_user_id=u-7");
    await userEvent.click(screen.getByRole("radio", { name: "Disposed" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?officer=u-7&case_state=disposed");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ case_state: "disposed" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("case_state=disposed"));
  });

  it("a row opens the case page; there is no release or return to the pool", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open WP(C)/1/2026" }));
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000001");
    expect(screen.queryByRole("button", { name: /release|return|unclaim/i })).toBeNull();
  });

  it("the default department of a two-department login is the one read whole", async () => {
    const two = admin(undefined, { memberships: [membership("EDU", ["cases.view_scope"]), membership("HEALTH", ["cases.view_scope", "cases.claim"], false)] });
    const api = browserApi(
      routes({
        "GET /me": two,
        "GET /inbox/counts": { departments: [block("EDU", { whole_department: false }), block("HEALTH")] },
      }),
    );
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("office=HEALTH");
  });
});

describe("old addresses", () => {
  it("/inbox and /cases open the first tab the login may open, keeping the query string, or /search", async () => {
    resetNav("/inbox");
    browserApi({ "GET /me": officer() });
    const { unmount } = renderWithClient(<InboxIndex params={{ q: "ram" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/working?q=ram"));
    unmount();
    resetNav("/cases");
    browserApi({ "GET /me": makeMe(["cases.view_all"], "state_oversight") });
    const { unmount: u2 } = renderWithClient(<InboxIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/sent"));
    u2();
    resetNav("/cases");
    browserApi({ "GET /me": makeMe(["users.view"], "dept_admin") });
    renderWithClient(<InboxIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/search"));
  });

  it("the old Cases list addresses land on the Case inbox tabs with the query kept", async () => {
    expect(redirectTarget(OLD_CASES_REDIRECTS["/cases/with-me"]!, { overdue: "true", q: "ram" })).toBe("/inbox/working?overdue=true&q=ram");
    expect(redirectTarget(OLD_CASES_REDIRECTS["/cases/with-me"]!, { held: "offices" })).toBe("/inbox/working?held=offices");
    expect(redirectTarget(OLD_CASES_REDIRECTS["/cases/sent"]!, {})).toBe("/inbox/sent");
    expect(redirectTarget(OLD_CASES_REDIRECTS["/cases/pending"]!, { holder_department: "HEALTH" })).toBe(
      "/inbox/pending?holder_department=HEALTH",
    );
    resetNav("/cases/with-me");
    renderWithClient(<Redirect to={OLD_CASES_REDIRECTS["/cases/with-me"]!} params={{ overdue: "true", q: "ram" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/working?overdue=true&q=ram"));
  });

  it("/files/* and /inbox/files point to final addresses, keeping the query string", async () => {
    expect(redirectTarget(OLD_FILES_REDIRECTS["/files/mine"]!, { overdue: "true", q: "ram" })).toBe("/inbox/working?overdue=true&q=ram");
    expect(redirectTarget(OLD_FILES_REDIRECTS["/files/offices"]!, { overdue: "true" })).toBe("/inbox/working?overdue=true&held=offices");
    expect(redirectTarget(OLD_FILES_REDIRECTS["/files/department"]!, { holder_department: "HEALTH" })).toBe(
      "/inbox/pending?holder_department=HEALTH",
    );
    expect(redirectTarget(OLD_FILES_REDIRECTS["/files/sent"]!, {})).toBe("/inbox/sent");
    expect(redirectTarget(OLD_FILES_REDIRECTS["/files"]!, {})).toBe("/inbox/working");
    expect(redirectTarget(OLD_FILES_REDIRECTS["/inbox/files"]!, {})).toBe("/inbox/working");
    const sources = new Set([
      ...Object.keys(OLD_FILES_REDIRECTS),
      ...Object.keys(OLD_CASES_REDIRECTS),
      ...Object.keys(OLD_INBOX_REDIRECTS),
      "/cases",
      "/inbox",
      "/inbox/claimed",
    ]);
    for (const target of [...Object.values(OLD_FILES_REDIRECTS), ...Object.values(OLD_CASES_REDIRECTS)]) {
      expect(sources.has(target.split("?")[0]!), target).toBe(false);
    }
  });

  it("/inbox/claimed goes to Department cases for a whole-department reader, keeping the query string", async () => {
    browserApi(routes());
    renderWithClient(<ClaimedRedirect params={{ department: "EDU", case_state: "disposed" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/department?department=EDU&case_state=disposed"));
  });

  it("/inbox/claimed goes to Working on for an officer", async () => {
    browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": { departments: [block("EDU", { whole_department: false })] } }));
    renderWithClient(<ClaimedRedirect params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/working"));
  });
});

/**
 * The Case inbox = the user's own work (design portal-ui-redesign, decisions 5 and 10.4; case-inbox-simplify): the four
 * tabs per login with the one count on With Me, With Me (Show, the Next Hearing column, Overdue Only and the side panel
 * with the remark), My Cases (view=all, the Reason badges, no status switch), Sent by Me (still out by default),
 * Department (no status switch, the Quick Filters, the tracker's list and the folded Tracking Summary), and the old
 * addresses. Recommended, the pool and Transfers are tested with Case claim (`components/claim/claim.test.tsx`); the
 * held and sent lists in detail in `components/files/cases-list.test.tsx`.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseSummary, CustodyBrief, CustodyCard, CustodySummary, HeldItem, Me, Ownership, Permission } from "@/lib/api/types";
import { setFlash } from "@/lib/flash";
import { addDays, istDay } from "@/lib/format";
import { admin, block, membership, myCase, officer, summary } from "@/test/claimFixtures";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { InboxFrame, InboxIndex } from "./InboxFrame";
import { ClaimedRedirect, OldInboxRedirect } from "./Redirects";
import { courtNext } from "@/test/nextHearing";

const COUNTS = { working: 5, files: 2, all: 9, claimed: 7, disposed: 1 };

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

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: true,
    can_send: true,
    due_date: "2026-10-10",
    holder_office: { code: "EDU", name: "Education" },
    holder_user: { id: "u-1", full_name: "Anita Sharma", designation: "Under Secretary" },
    leg_seq_no: 2,
    overdue: true,
    overdue_days: 3,
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    reason: "sent",
    remark: "please send parawise comments",
    sent_by: { name: "Edu Admin", designation: "Joint Secretary", office_code: "EDU" },
    since: "2026-10-01T10:00:00Z",
    ...extra,
  };
}

function heldItem(n: number, c: Partial<CaseSummary> = {}, extra: Partial<CustodyCard> = {}): HeldItem {
  return { case: summary(n, c), card: card(extra) };
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

/** A tracker by a per-user override, without whole-department sight (decision 11). */
function trackerOnly(): Me {
  return officer(["cases.view_scope", "custody.track"]);
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
const NOT_WHOLE = { departments: [block("EDU", { whole_department: false })] };

beforeEach(() => {
  resetNav("/inbox/with-me");
});

describe("tabs (case-inbox-simplify, decisions 1 and 3)", () => {
  it("a department officer sees With Me, My Cases and Sent by Me; only With Me has a count, from files; no summary is read", async () => {
    const api = browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": NOT_WHOLE }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/inbox/with-me", "/inbox/my-cases", "/inbox/sent"]);
    expect(within(tabs).getByRole("link", { name: /With Me.*\(2\)/ })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "My Cases" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Sent by Me" })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: /Working On|Claimed by Me|Disposed|Department|Pending Action/ })).toBeNull();
    expect(api.calls.some((c) => c.path.startsWith("/custody/summary"))).toBe(false);
  });

  it("a department head sees all four tabs in order; only With Me carries a count", async () => {
    const api = browserApi(routes({ "GET /me": head() }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/inbox/with-me",
      "/inbox/my-cases",
      "/inbox/sent",
      "/inbox/department",
    ]);
    expect(within(tabs).getAllByRole("link").map((a) => a.textContent)).toEqual(["With Me2 (2)", "My Cases", "Sent by Me", "Department"]);
    await waitFor(() => expect(api.calls.filter((c) => c.path.startsWith("/custody/summary"))).toHaveLength(1));
  });

  it("State oversight (cases.view_all without cases.view_scope) sees With Me, Sent by Me and Department", async () => {
    const reader = makeMe(["cases.view_all"], "state_oversight", { memberships: [] });
    const api = browserApi(routes({ "GET /me": reader, "GET /inbox/counts": { departments: [block(null, { whole_department: false })] } }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/inbox/with-me", "/inbox/sent", "/inbox/department"]);
    expect(api.calls.some((c) => c.path.startsWith("/inbox/mine/counts"))).toBe(false);
  });

  it("a tracker by override without whole-department sight gets Department too", async () => {
    browserApi(routes({ "GET /me": trackerOnly(), "GET /inbox/counts": NOT_WHOLE }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case Inbox Sections" });
    expect(within(tabs).getByRole("link", { name: "Department" })).toHaveAttribute("href", "/inbox/department");
  });

  it("a tab the login may not open shows the not-found text", async () => {
    resetNav("/inbox/department");
    browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": NOT_WHOLE }));
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    expect(await screen.findByText("The page does not exist, or you cannot see it.")).toBeInTheDocument();
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

  it("a State-wide reader gets Department and picks any department", async () => {
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
    expect(await screen.findByRole("link", { name: "Department" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("combobox", { name: "Department" })).toHaveValue("FIN");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Department" }), "EDU");
    expect(nav.push).toHaveBeenCalledWith("/inbox/department?department=EDU");
  });
});

describe("With Me (decision 2)", () => {
  it("reads /custody/held?scope=me; Show is With Me or With My Offices, no All; an incoming held=me is the default", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="with-me" params={{ held: "me" }} />);
    const show = await screen.findByRole("radiogroup", { name: "Show" });
    expect(within(show).getAllByRole("radio").map((r) => r.textContent)).toEqual(["With Me", "With My Offices"]);
    expect(within(show).getByRole("radio", { name: "With Me" })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("scope=me"));
    expect(api.calls.some((c) => c.path.startsWith("/inbox/mine?"))).toBe(false);
    unmount();
    renderWithClient(<InboxFrame tab="with-me" params={{ held: "offices" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("scope=office"));
  });

  it("the Next Hearing column shows HearingDate; a disposed case with me reads Disposed", async () => {
    const soon = addDays(istDay(), 1);
    browserApi(
      routes({
        "GET /custody/held": {
          items: [heldItem(1, { next_hearing: courtNext(soon) }), heldItem(2, { status: "disposed" }, { overdue: false, overdue_days: 0, due_date: null })],
          total: 2,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    const table = await screen.findByRole("table", { name: "Cases with Me" });
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
    expect(row1.querySelector('[data-band="tomorrow"]')).toHaveTextContent("Tomorrow");
    const row2 = screen.getByRole("row", { name: "Details of WP(C)/2/2026" });
    expect(row2.querySelector("[data-band]")).toHaveAttribute("data-band", "disposed");
    expect(within(row2).getByText("Disposed")).toBeInTheDocument();
  });

  it("Overdue Only sends overdue=true; an incoming action=overdue reads as overdue=true", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="with-me" params={{ overdue: "true" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("overdue=true"));
    expect(screen.getByLabelText("Overdue Only")).toBeChecked();
    unmount();
    renderWithClient(<InboxFrame tab="with-me" params={{ action: "overdue" }} />);
    await waitFor(() => expect(screen.getByLabelText("Overdue Only")).toBeChecked());
    const url = lastUrl(api.calls, "/custody/held?");
    expect(url).toContain("overdue=true");
    expect(url).not.toContain("action=");
  });

  it("a row opens the side panel with the card's remark", async () => {
    browserApi(routes({ "GET /custody/held": { items: [heldItem(1)], total: 1 } }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/1/2026" }));
    const panel = await screen.findByRole("dialog", { name: "Case Details" });
    expect(within(panel).getByText("please send parawise comments")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: /send|recall/i })).toBeNull();
  });
});

describe("My Cases (decision 4)", () => {
  beforeEach(() => resetNav("/inbox/my-cases"));

  it("reads view=all with no status switch and no case_state, even when the URL carries one", async () => {
    const api = browserApi(routes());
    renderWithClient(<InboxFrame tab="mine" params={{ case_state: "disposed", action: "overdue" }} />);
    await screen.findByText("Nothing waiting");
    const url = lastUrl(api.calls, "/inbox/mine?");
    expect(url).toContain("view=all");
    expect(url).not.toContain("case_state");
    expect(url).not.toContain("action=");
    expect(screen.queryByRole("radiogroup", { name: /Status|Cases/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Disposed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Action Overdue" })).toBeNull();
    expect(screen.getByText("Cases assigned to you, cases you claimed and cases sent to you appear here.")).toBeInTheDocument();
  });

  it("the Reason badges come in the order Assigned to Me, Claimed by Me, With Me; a disposed row reads Disposed; Your Action only with me", async () => {
    const api = browserApi(
      routes({
        "GET /inbox/mine": {
          items: [
            myCase(1, { custody: brief(), reasons: ["file", "allotted"] }),
            myCase(2, { reasons: ["claimed"], custody: brief({ with_me: false }) }),
            myCase(3, { case: summary(3, { status: "disposed" }), reasons: ["claimed", "file", "allotted"], custody: brief() }),
          ],
          total: 3,
        },
      }),
    );
    renderWithClient(<InboxFrame tab="mine" params={{}} />);
    const table = await screen.findByRole("table", { name: "My Cases" });
    expectDataTable(table);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Case",
      "Reason",
      "Stage",
      "Next Hearing",
      "Your Action",
      "Actions",
    ]);
    const badges = (n: number) =>
      Array.from(screen.getByRole("row", { name: `Open WP(C)/${n}/2026` }).querySelectorAll("td")[1]!.querySelectorAll("[title]")).map(
        (b) => b.textContent,
      );
    expect(badges(1)).toEqual(["Assigned to Me", "With Me"]);
    expect(badges(2)).toEqual(["Claimed by Me"]);
    expect(badges(3)).toEqual(["Assigned to Me", "Claimed by Me", "With Me"]);
    const row3 = screen.getByRole("row", { name: "Open WP(C)/3/2026" });
    expect(row3.querySelector("[data-band]")).toHaveAttribute("data-band", "disposed");
    expect(within(screen.getByRole("row", { name: "Open WP(C)/1/2026" })).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: "Open WP(C)/2/2026" })).queryByText("Parawise comments")).toBeNull();
    expect(screen.getByText("3 cases")).toBeInTheDocument();
    expect(lastUrl(api.calls, "/inbox/mine?")).toContain("view=all");
    await userEvent.click(row3);
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GHC-CASE-2026-000003");
  });

  it("the quick chip writes next=n7; the filtered count reads n of m, m being the all figure", async () => {
    const api = browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { unmount } = renderWithClient(<InboxFrame tab="mine" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Hearing This Week" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/my-cases?next=n7");
    unmount();
    renderWithClient(<InboxFrame tab="mine" params={{ next: "n7", stage: "none" }} />);
    expect(await screen.findByText("1 of 9 cases")).toBeInTheDocument();
    const url = lastUrl(api.calls, "/inbox/mine?");
    for (const part of ["view=all", "stage=none", `next_from=${istDay()}`]) expect(url).toContain(part);
  });

  it("Search Words and Stage are on the first row; case type, year and court are under More filters (list-search, decision 17)", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="mine" params={{}} />);
    const stage = await screen.findByLabelText("Stage");
    await waitFor(() => expect(within(stage).getByRole("option", { name: "Counsel briefed" })).toBeInTheDocument());
    expect(screen.queryByLabelText("Year")).toBeNull();
    expect(screen.getByLabelText(/^Words/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More Filters" }));
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
    expect(screen.getByLabelText("Court")).toBeInTheDocument();
  });

  it("a filtered empty list says No cases match these filters., and Clear All keeps the sort (list-search, decisions 18 and 35)", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="mine" params={{ q: "zebra", sort: "case_no", dir: "asc" }} />);
    const none = await screen.findByText("No cases match these filters.");
    await userEvent.click(within(none.parentElement!).getByRole("button", { name: "Clear All" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/my-cases?sort=case_no&dir=asc");
  });

  it("the page has at most one primary button (decision 16)", async () => {
    browserApi(routes({ "GET /inbox/mine": { items: [myCase(1)], total: 1 } }));
    const { container } = renderWithClient(<InboxFrame tab="mine" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });
});

describe("Sent by Me (decision 6)", () => {
  beforeEach(() => resetNav("/inbox/sent"));

  it("the default reads still_out=true; Show Earlier reads without it", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="sent" params={{}} />);
    expect(await screen.findByText(/Nothing you sent is still out/)).toBeInTheDocument();
    expect(lastUrl(api.calls, "/custody/sent?")).toContain("still_out=true");
    unmount();
    renderWithClient(<InboxFrame tab="sent" params={{ earlier: "true" }} />);
    expect(await screen.findByText("You have not sent or recalled a case.")).toBeInTheDocument();
    expect(lastUrl(api.calls, "/custody/sent?")).not.toContain("still_out");
  });
});

describe("Department (decisions 9 to 14)", () => {
  beforeEach(() => resetNav("/inbox/department"));

  it("the filter grid: Search, Responsible Unit, Dealing Officer, Stage, Next hearing; More filters slides open with the rest; no status switch", async () => {
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(within(row).getByText("EDU-DSE")).toBeInTheDocument();
    expect(within(row).getByText("Officer One", { exact: false })).toBeInTheDocument();
    expect(within(row).getByText("Affidavit filed")).toBeInTheDocument();
    expect(within(row).getByText("Health Officer", { exact: false })).toBeInTheDocument();
    for (const label of ["Responsible Unit", "Dealing Officer", "Stage", "Next Hearing"]) expect(screen.getByLabelText(label)).toBeInTheDocument();
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
    expect(screen.queryByRole("radio", { name: "Active" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "Disposed" })).toBeNull();
  });

  it("Layout B: Words is the hero; Responsible Unit, Dealing Officer, Stage, Next Hearing and Case Type on the right; the count in the strip (portal-ui-polish-2, decision 23)", async () => {
    const api = browserApi(routes());
    const { container } = renderWithClient(<InboxFrame tab="department" params={{ q: "ram", year: "2025" }} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    const hero = container.querySelector<HTMLElement>("[data-zone='hero']")!;
    expect(within(hero).getByLabelText(/^Words/)).toHaveValue("ram");
    const fields = container.querySelector<HTMLElement>("[data-zone='fields']")!;
    for (const label of ["Responsible Unit", "Dealing Officer", "Stage", "Next Hearing", "Case Type"]) {
      expect(within(fields).getByLabelText(label)).toBeInTheDocument();
    }
    const more = container.querySelector<HTMLElement>("[data-zone='more']")!;
    expect(screen.getByRole("button", { name: "More Filters (1)" })).toHaveAttribute("aria-expanded", "true");
    for (const label of ["Year", "Court", "With", "Action"]) expect(within(more).getByLabelText(label)).toBeInTheDocument();
    const strip = container.querySelector<HTMLElement>("[data-zone='summary']")!;
    expect(within(strip).getByText(/cases/)).toBeInTheDocument();
    expect(within(strip).getByText("Year: 2025")).toBeInTheDocument();
    const url = lastUrl(api.calls, "/inbox/claimed?");
    expect(url).toContain("q=ram");
    expect(url).toContain("year=2025");
  });

  it("the request carries case_state=all whatever the URL says; m of n of m is claimed_active + claimed_disposed", async () => {
    const api = browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{ case_state: "disposed", officer: "none", next: "n7", holder: "elsewhere", action: "overdue" }} />);
    expect(await screen.findByText("1 of 5 cases")).toBeInTheDocument();
    const url = lastUrl(api.calls, "/inbox/claimed?");
    for (const part of ["office=EDU", "case_state=all", "unallotted=true", "holder=elsewhere", "action=overdue", "next_from="]) {
      expect(url).toContain(part);
    }
    expect(url).not.toContain("case_state=disposed");
    expect(url).not.toContain("officer_user_id");
    const chips = screen.getByRole("list", { name: "Applied Filters" });
    expect(within(chips).getByText("Dealing Officer: Not Assigned Yet")).toBeInTheDocument();
    expect(within(chips).getByText("With: Another Office")).toBeInTheDocument();
  });

  it("Not Assigned Yet sends unallotted=true; removing a chip applies at once", async () => {
    const api = browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    const officerSelect = await screen.findByLabelText("Dealing Officer");
    await waitFor(() => expect(within(officerSelect).getByRole("option", { name: "Officer One" })).toBeInTheDocument());
    await userEvent.selectOptions(officerSelect, "none");
    await userEvent.selectOptions(screen.getByLabelText("Next Hearing"), "n7");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?next=n7&officer=none");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ officer: "none", next: "n7" }} />);
    await screen.findByText("1 of 5 cases");
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("unallotted=true");
    await userEvent.click(screen.getByRole("button", { name: "Remove filter Dealing Officer: Not Assigned Yet" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?next=n7");
  });

  it("Quick Filters: Overdue sets action=overdue, With Another Office sets holder=elsewhere; each agrees with its More Filters select", async () => {
    browserApi(routes());
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    const quick = await screen.findByRole("group", { name: "Quick Filters" });
    await userEvent.click(within(quick).getByRole("button", { name: "Overdue" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?action=overdue");
    const elsewhere = within(quick).getByRole("button", { name: "With Another Office" });
    expect(elsewhere).toHaveAccessibleDescription("Outside this department and its units.");
    await userEvent.click(elsewhere);
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?holder=elsewhere");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ action: "overdue", holder: "elsewhere" }} />);
    const quick2 = await screen.findByRole("group", { name: "Quick Filters" });
    expect(within(quick2).getByRole("button", { name: "Overdue" })).toHaveAttribute("aria-pressed", "true");
    expect(within(quick2).getByRole("button", { name: "With Another Office" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Action")).toHaveValue("overdue");
    expect(screen.getByLabelText("With")).toHaveValue("elsewhere");
    expect(within(screen.getByLabelText("With")).getByRole("option", { name: "Another Office" })).toHaveValue("elsewhere");
  });

  it("DepartmentCases wording: Responsible Unit · Dealing Officer, Not Assigned, Not Assigned Yet (claim-assign-wording, decision 5)", async () => {
    browserApi(routes({ "GET /inbox/claimed": { items: [ownership(1), ownership(2, { unit: null, officer: null })], total: 2 } }));
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(screen.getByRole("columnheader", { name: "Responsible Unit · Dealing Officer" })).toBeInTheDocument();
    const bare = screen.getByRole("row", { name: "Open WP(C)/2/2026" });
    expect(within(bare).getByText("Not Assigned")).toBeInTheDocument();
    const officerSelect = screen.getByLabelText("Dealing Officer");
    expect(within(officerSelect).getByRole("option", { name: "Not Assigned Yet" })).toHaveValue("none");
    expect(document.body.textContent).not.toMatch(/allot/i);
  });

  it("an officer chosen sends officer_user_id; a row opens the case page; there is no release or return to the pool", async () => {
    const api = browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{ officer: "u-7" }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open WP(C)/1/2026" }));
    expect(lastUrl(api.calls, "/inbox/claimed?")).toContain("officer_user_id=u-7");
    expect(nav.push).toHaveBeenCalledWith("/cases/ASLMS-GHC-CASE-2026-000001");
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

  it("the Tracking Summary is folded and shown only to a tracker of the selected department", async () => {
    const api = browserApi(routes({ "GET /me": head() }));
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    const toggle = await screen.findByRole("button", { name: "Tracking Summary" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Tracking summary: EDU" })).toBeNull();
    await userEvent.click(toggle);
    expect(await screen.findByRole("region", { name: "Tracking summary: EDU" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Tracking summary: FIN" })).toBeNull();
    unmount();
    // the department admin of this fixture does not track: no summary request, no section
    const calls = api.calls.length;
    browserApi(routes());
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    expect(screen.queryByRole("button", { name: "Tracking Summary" })).toBeNull();
    expect(calls).toBeGreaterThan(0);
  });

  it("a tracker without whole-department sight gets the tracked list narrowed to the department; its Overdue chip sends overdue=true", async () => {
    const api = browserApi(routes({ "GET /me": trackerOnly(), "GET /inbox/counts": NOT_WHOLE }));
    const { unmount } = renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByText("No case of your department is waiting on someone.");
    const url = lastUrl(api.calls, "/custody/held?");
    expect(url).toContain("scope=owned");
    expect(url).toContain("owner=EDU");
    expect(api.calls.some((c) => c.path.startsWith("/inbox/claimed"))).toBe(false);
    const quick = screen.getByRole("group", { name: "Quick Filters" });
    expect(within(quick).queryByRole("button", { name: "With Another Office" })).toBeNull();
    await userEvent.click(within(quick).getByRole("button", { name: "Overdue" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/department?action=overdue");
    unmount();
    renderWithClient(<InboxFrame tab="department" params={{ action: "overdue" }} />);
    await waitFor(() => expect(lastUrl(api.calls, "/custody/held?")).toContain("overdue=true"));
    expect(screen.getByRole("button", { name: "Tracking Summary" })).toBeInTheDocument();
  });
});

describe("old addresses (decision 15)", () => {
  it("/inbox and /cases open the first tab the login may open, keeping the query string, or /search", async () => {
    resetNav("/inbox");
    browserApi({ "GET /me": officer() });
    const { unmount } = renderWithClient(<InboxIndex params={{ q: "ram" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/with-me?q=ram"));
    unmount();
    resetNav("/cases");
    browserApi({ "GET /me": makeMe(["cases.view_all"], "state_oversight") });
    const { unmount: u2 } = renderWithClient(<InboxIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/with-me"));
    u2();
    resetNav("/cases");
    browserApi({ "GET /me": makeMe(["users.view"], "dept_admin") });
    renderWithClient(<InboxIndex />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/search"));
  });

  for (const [from, params, to] of [
    ["/inbox/working", { held: "offices" }, "/inbox/with-me?held=offices"],
    ["/inbox/working", { overdue: "true", q: "ram" }, "/inbox/with-me?q=ram&overdue=true"],
    ["/inbox/working", { q: "ram" }, "/inbox/my-cases?q=ram"],
    ["/inbox/claimed-by-me", {}, "/inbox/my-cases"],
    ["/inbox/disposed", { q: "x" }, "/inbox/my-cases?q=x"],
    ["/inbox/pending", { overdue: "true", owner: "EDU" }, "/inbox/department?action=overdue&department=EDU"],
    ["/cases/pending", {}, "/inbox/department"],
    ["/cases/with-me", {}, "/inbox/with-me"],
    ["/files/department", {}, "/inbox/department"],
  ] as const) {
    it(`${from}${Object.keys(params).length ? "?" + new URLSearchParams(params).toString() : ""} lands on ${to}`, async () => {
      resetNav(from);
      renderWithClient(<OldInboxRedirect from={from} params={{ ...params }} />);
      await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(to));
    });
  }

  it("/inbox/claimed goes to Department for a whole-department reader, keeping the query string", async () => {
    browserApi(routes());
    renderWithClient(<ClaimedRedirect params={{ department: "EDU", case_state: "disposed" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/department?department=EDU&case_state=disposed"));
  });

  it("/inbox/claimed goes to My Cases for an officer", async () => {
    browserApi(routes({ "GET /me": officer(), "GET /inbox/counts": NOT_WHOLE }));
    renderWithClient(<ClaimedRedirect params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/inbox/my-cases"));
  });
});

describe("the Next Hearing column's bands (design next-hearing-highlight, decisions 4, 9 and 11)", () => {
  const today = istDay();
  const rows = [
    summary(1, { next_hearing: courtNext(today) }),
    summary(2, { next_hearing: courtNext(addDays(today, 3)) }),
    summary(3, { next_hearing: courtNext(addDays(today, 20)) }),
    summary(4, { next_hearing: courtNext(addDays(today, 1)), status: "disposed" }),
    summary(5, { next_hearing: courtNext(addDays(today, -5)) }),
    summary(6, { next_hearing: courtNext(null) }),
  ];
  const expected = [
    ["today", "Today"],
    ["week", "In 3 Days"],
    ["later", null],
    ["disposed", "Disposed"],
    ["passed", "Date Passed"],
    ["none", "No Date Yet"],
  ] as const;

  function check(name: (n: number) => string) {
    expected.forEach(([band, word], i) => {
      const row = screen.getByRole("row", { name: name(i + 1) });
      const el = row.querySelector("[data-band]")!;
      expect(el).toHaveAttribute("data-band", band);
      if (word) expect(el.firstElementChild).toHaveTextContent(word);
      // the later band reads the date alone in a list
      else expect(el.textContent).toMatch(/^\d{1,2} [A-Z][a-z]{2} \d{4}$/);
    });
    expect(screen.queryByText("48 Hours")).toBeNull();
    expect(screen.queryByText("This Week", { selector: "span" })).toBeNull();
  }

  it("With Me", async () => {
    browserApi(routes({ "GET /custody/held": { items: rows.map((c): HeldItem => ({ case: c, card: card() })), total: rows.length } }));
    renderWithClient(<InboxFrame tab="with-me" params={{}} />);
    await screen.findByRole("table", { name: "Cases with Me" });
    check((n) => `Details of WP(C)/${n}/2026`);
  });

  it("My Cases", async () => {
    resetNav("/inbox/my-cases");
    browserApi(routes({ "GET /inbox/mine": { items: rows.map((c, i) => myCase(i + 1, { case: c, reasons: ["claimed"] })), total: rows.length } }));
    renderWithClient(<InboxFrame tab="mine" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    check((n) => `Open WP(C)/${n}/2026`);
  });

  it("Department", async () => {
    resetNav("/inbox/department");
    browserApi(routes({ "GET /inbox/claimed": { items: rows.map((c, i) => ownership(i + 1, { case: c })), total: rows.length } }));
    renderWithClient(<InboxFrame tab="department" params={{}} />);
    await screen.findByRole("row", { name: "Open WP(C)/1/2026" });
    check((n) => `Open WP(C)/${n}/2026`);
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseSummary, InboxCounts, Me, Permission, Recommendation, Transfer } from "@/lib/api/types";
import { istDay } from "@/lib/format";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { InboxFrame } from "./InboxFrame";

const ADMIN_FNS: Permission[] = [
  "cases.view_scope",
  "cases.claim",
  "cases.dismiss",
  "cases.suggest_elsewhere",
  "cases.allot",
  "cases.transfer_request",
  "cases.transfer_decide",
  "cases.release",
];

function membership(code: string, functions: Permission[], primary = true) {
  return {
    id: `m-${code}`,
    office: { code, name: code, kind: "department" },
    department_code: code,
    designation: null,
    role: "dept_admin" as const,
    is_primary: primary,
    is_active: true,
    functions,
  };
}

function admin(functions: Permission[] = ADMIN_FNS, extra: Partial<Me> = {}): Me {
  return makeMe(functions, "dept_admin", { memberships: [membership("EDU", functions)], ...extra });
}

function block(code: string | null, extra: Partial<InboxCounts> = {}): InboxCounts {
  return {
    office_code: code,
    recommended_high: 2,
    recommended_medium: 1,
    claimed_active: 4,
    claimed_disposed: 1,
    transfers_in_open: 1,
    pool_with_hearing_7d: 3,
    ...extra,
  };
}

function summary(n: number, extra: Partial<CaseSummary> = {}): CaseSummary {
  return {
    id: `c-${n}`,
    ref_no: `ASLMS/GOA/CASE/2026/00000${n}`,
    cnr: `ASHC01000${n}002026`,
    case_no_text: `WP(C)/${n}/2026`,
    is_provisional: false,
    petitioner_summary: "RAM KUMAR",
    respondent_summary: "STATE OF ASSAM",
    status: "pending",
    next_hearing_date: null,
    last_listed_on: "2026-09-25",
    last_listing: { list_date: "2026-09-25", list_type: "daily", court_no: "3", sr_no: 41 },
    ...extra,
  };
}

function rec(n: number, extra: Partial<Recommendation> = {}): Recommendation {
  return {
    id: `r-${n}`,
    case: summary(n),
    office_code: "EDU",
    score: 0.849,
    band: "medium",
    status: "recommended",
    origin: "cause_list",
    signals: [
      { kind: "counsel_code", matched: "SC, EDU" },
      { kind: "linked_case", matched: "WP(C)/2417/2026" },
    ],
    suggested_by_office_code: null,
    reason: null,
    created_at: "2026-10-01T10:00:00Z",
    acted_at: null,
    current_owner_code: null,
    ...extra,
  };
}

function transfer(n: number, extra: Partial<Transfer> = {}): Transfer {
  return {
    id: `t-${n}`,
    ref_no: `ASLMS/EDU/TRF/2026/00000${n}`,
    case: summary(n),
    from_office_code: "HEALTH",
    to_office_code: "EDU",
    status: "requested",
    reason: "theirs",
    stay_as_watcher: false,
    decision_note: null,
    requested_by: { id: "u-2", full_name: "Health Admin" },
    requested_at: "2026-10-01T10:00:00Z",
    decided_by: null,
    decided_at: null,
    withdrawn_at: null,
    ...extra,
  };
}

const DEPARTMENTS = {
  departments: [
    { code: "EDU", name: "Education" },
    { code: "HEALTH", name: "Health" },
    { code: "FIN", name: "Finance" },
  ],
  items: [],
  units: [],
  total: 3,
};

beforeEach(() => {
  resetNav("/inbox/recommended");
});

describe("tabs and departments", () => {
  it("a tab whose count is null is not shown", async () => {
    const me = admin(["cases.view_scope"]);
    browserApi({
      "GET /me": me,
      "GET /inbox/counts": {
        departments: [
          block("EDU", { recommended_high: null, recommended_medium: null, transfers_in_open: null, pool_with_hearing_7d: null }),
        ],
      },
      "GET /inbox/claimed": { items: [], total: 0 },
    });
    renderWithClient(<InboxFrame tab="claimed" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Inbox sections" });
    expect(within(tabs).getByRole("link", { name: "Claimed (4)" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).queryByRole("link", { name: /Recommended/ })).toBeNull();
    expect(within(tabs).queryByRole("link", { name: /Unclaimed pool/ })).toBeNull();
    expect(within(tabs).queryByRole("link", { name: /Transfers/ })).toBeNull();
    expect(screen.queryByLabelText("Department")).toBeNull(); // one department: no selector
  });

  it("tab badges come from the counts; the pool has none", async () => {
    browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [], total: 0 },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Inbox sections" });
    expect(within(tabs).getByRole("link", { name: "Recommended (3)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Transfers (1)" })).toBeInTheDocument();
    expect(within(tabs).getByRole("link", { name: "Unclaimed pool" })).toBeInTheDocument();
    expect(screen.getByText(/No case is assigned automatically/)).toBeInTheDocument();
  });

  it("the selector appears with two departments and moves to the chosen one", async () => {
    const me = admin(ADMIN_FNS, {
      memberships: [membership("EDU", ADMIN_FNS), membership("HEALTH", ["cases.view_scope"], false)],
    });
    browserApi({
      "GET /me": me,
      "GET /inbox/counts": { departments: [block("EDU"), block("HEALTH", { recommended_high: null, recommended_medium: null })] },
      "GET /inbox/recommended": { items: [], total: 0 },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    const select = await screen.findByLabelText("Department");
    await userEvent.selectOptions(select, "HEALTH");
    expect(nav.push).toHaveBeenCalledWith("/inbox/recommended?department=HEALTH");
  });

  it("a cases.view_all reader picks any department and sees no action buttons there", async () => {
    const reader = makeMe(["cases.view_scope", "cases.view_all", "cases.suggest_elsewhere"], "state_oversight", {
      memberships: [],
    });
    const api = browserApi({
      "GET /me": reader,
      "GET /inbox/counts": (call: { url: string }) =>
        call.url.includes("office=FIN") ? { departments: [block("FIN", { transfers_in_open: null })] } : { departments: [block(null, {
          recommended_high: null, recommended_medium: null, claimed_active: null, claimed_disposed: null, transfers_in_open: null,
        })] },
      "GET /custody/recipients": DEPARTMENTS,
      "GET /inbox/recommended": { items: [rec(1)], total: 1 },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{ department: "FIN" }} />);
    expect(await screen.findByText("WP(C)/1/2026")).toBeInTheDocument();
    expect(screen.getByLabelText("Department")).toHaveValue("FIN");
    expect(screen.getByText(/actions are for its own officers/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Claim" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(api.calls.some((c) => c.url.includes("/inbox/recommended?office=FIN"))).toBe(true);
  });
});

describe("Recommended", () => {
  it("shows the API's band label, the signal chips and the latest listing", async () => {
    browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": {
        items: [rec(1), rec(2, { score: 0.912, band: "high", origin: "suggestion", suggested_by_office_code: "FIN", reason: "school land", current_owner_code: "HEALTH" })],
        total: 2,
      },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    const first = (await screen.findByText("WP(C)/1/2026")).closest("tr")!;
    expect(within(first).getByText("0.849")).toBeInTheDocument();
    expect(within(first).getByText("POSSIBLE")).toBeInTheDocument(); // the API's band, not 0.849 ≥ 0.85
    expect(within(first).getByText("Code: SC, EDU")).toBeInTheDocument();
    expect(within(first).getByText("Linked: WP(C)/2417/2026")).toBeInTheDocument();
    expect(within(first).getByText(/Cause list 25 Sep 2026 · Court 3 · Item 41/)).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute(
      "href",
      "/cases/ASLMS-GOA-CASE-2026-000001",
    );
    const second = screen.getByText("WP(C)/2/2026").closest("tr")!;
    expect(within(second).getByText("STRONG")).toBeInTheDocument();
    expect(within(second).getByText("Suggested by FIN: school land")).toBeInTheDocument();
    expect(within(second).getByText("Owned by HEALTH")).toBeInTheDocument();
  });

  it("the cause-list filter sends listed_from / listed_to", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [], total: 0 },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{ listed: "today" }} />);
    const today = istDay();
    await waitFor(() =>
      expect(api.calls.some((c) => c.url.includes(`listed_from=${today}`) && c.url.includes(`listed_to=${today}`))).toBe(true),
    );
    await userEvent.selectOptions(screen.getByLabelText("Cause-list date"), "d7");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/recommended?listed=d7");
  });

  it("Claim sends the selected department and warns when another department owns the case", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1, { current_owner_code: "HEALTH" })], total: 1 },
      "GET /custody/recipients": {
        departments: [],
        items: [
          { membership_id: "mm-1", user_id: "u-7", full_name: "Officer One", designation: "SO", office_code: "EDU", office_name: "Education", role_label: "Officer" },
        ],
        units: [{ code: "EDU-DSE", name: "Secondary Education" }],
        total: 1,
      },
      "POST /cases/ASLMS-GOA-CASE-2026-000001/claim": json(201, {}),
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    expect(within(dialog).getByText(/owned by HEALTH; claiming adds your department as a watcher/)).toBeInTheDocument();
    expect(within(dialog).getByText("EDU")).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: /Officer One/ })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Officer"), "u-7");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ office_code: "EDU", officer_user_id: "u-7" });
  });

  it("the allot fields show only with cases.allot", async () => {
    const fns = ADMIN_FNS.filter((f) => f !== "cases.allot");
    browserApi({
      "GET /me": admin(fns),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1)], total: 1 },
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    expect(within(dialog).queryByLabelText("Officer")).toBeNull();
    expect(within(dialog).queryByLabelText("Unit")).toBeNull();
  });

  it("Suggest needs a reason, does not offer the selected department and sends it as from_office_code", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1)], total: 1 },
      "GET /custody/recipients": DEPARTMENTS,
      "POST /cases/ASLMS-GOA-CASE-2026-000001/suggest": {},
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Suggest department" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest another department" });
    await waitFor(() => expect(within(dialog).getByRole("option", { name: /HEALTH/ })).toBeInTheDocument());
    expect(within(dialog).queryByRole("option", { name: /^EDU/ })).toBeNull();
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "HEALTH");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest department" }));
    expect(within(dialog).getByText("A reason is required.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByLabelText("Reason (required)"), "health matter");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest department" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        office_code: "HEALTH",
        reason: "health matter",
        from_office_code: "EDU",
      }),
    );
  });

  it("Recommended's Suggest acts for the selected department of a two-department login", async () => {
    const twoDepartments = admin(ADMIN_FNS, {
      memberships: [membership("EDU", ADMIN_FNS), membership("HEALTH", ADMIN_FNS, false)],
    });
    const api = browserApi({
      "GET /me": twoDepartments,
      "GET /inbox/counts": { departments: [block("EDU"), block("HEALTH")] },
      "GET /inbox/recommended": { items: [rec(1, { office_code: "HEALTH", current_owner_code: "FIN" })], total: 1 },
      "GET /custody/recipients": DEPARTMENTS,
      "POST /cases/ASLMS-GOA-CASE-2026-000001/suggest": {},
    });
    renderWithClient(<InboxFrame tab="recommended" params={{ department: "HEALTH" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Suggest department" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest another department" });
    expect(within(dialog).getByText("HEALTH")).toBeInTheDocument(); // "Suggest from: HEALTH"
    const target = within(dialog).getByLabelText("Department");
    await waitFor(() => expect(within(target).getByRole("option", { name: /^EDU/ })).toBeInTheDocument());
    // neither the selected department nor the owner is offered
    expect(within(target).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a department", "EDU — Education"]);
    await userEvent.selectOptions(target, "EDU");
    await userEvent.type(within(dialog).getByLabelText("Reason (required)"), "education");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest department" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        office_code: "EDU",
        reason: "education",
        from_office_code: "HEALTH",
      }),
    );
  });

  it("the Pool's Suggest sends no originating department", async () => {
    resetNav("/inbox/pool");
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/pool": {
        items: [{ case: summary(1), best_score: 0.42, best_office_code: "FIN", dismissed_by: [] }],
        total: 1,
      },
      "GET /custody/recipients": DEPARTMENTS,
      "POST /cases/ASLMS-GOA-CASE-2026-000001/suggest": {},
    });
    renderWithClient(<InboxFrame tab="pool" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Suggest department" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest another department" });
    expect(within(dialog).queryByLabelText("Suggest from")).toBeNull();
    await waitFor(() => expect(within(dialog).getByRole("option", { name: /^FIN/ })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Department"), "FIN");
    await userEvent.type(within(dialog).getByLabelText("Reason (required)"), "finance matter");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest department" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "FIN", reason: "finance matter" }),
    );
  });

  it("Dismiss needs no reason", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1)], total: 1 },
      "POST /cases/ASLMS-GOA-CASE-2026-000001/dismiss": {},
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    const dialog = screen.getByRole("dialog", { name: "Dismiss this recommendation" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "EDU" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Dismiss and Allot act for the selected department, not the primary membership's", async () => {
    const twoDepartments = admin(ADMIN_FNS, {
      memberships: [membership("EDU", ADMIN_FNS), membership("HEALTH", ADMIN_FNS, false)],
    });
    const api = browserApi({
      "GET /me": twoDepartments,
      "GET /inbox/counts": { departments: [block("EDU"), block("HEALTH")] },
      "GET /inbox/recommended": { items: [rec(1, { office_code: "HEALTH" })], total: 1 },
      "GET /inbox/claimed": {
        items: [
          {
            id: "o-1",
            case: summary(1),
            office_code: "HEALTH",
            role: "watcher",
            status: "active",
            unit: null,
            officer: { id: "u-7", full_name: "Officer One" },
            claimed_at: "2026-10-01T10:00:00Z",
            allotted_at: null,
            released_at: null,
            release_reason: null,
          },
        ],
        total: 1,
      },
      "POST /cases/ASLMS-GOA-CASE-2026-000001/dismiss": {},
      "POST /cases/ASLMS-GOA-CASE-2026-000001/allot": {},
    });
    const { unmount } = renderWithClient(<InboxFrame tab="recommended" params={{ department: "HEALTH" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    let dialog = screen.getByRole("dialog", { name: "Dismiss this recommendation" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path.endsWith("/dismiss"))?.body).toEqual({
        office_code: "HEALTH",
      }),
    );
    unmount();
    renderWithClient(<InboxFrame tab="claimed" params={{ department: "HEALTH" }} />);
    const row = (await screen.findByText("WP(C)/1/2026")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Allot" }));
    dialog = screen.getByRole("dialog", { name: "Allot this case" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Officer"), "Clear");
    await userEvent.click(within(dialog).getByRole("button", { name: "Allot" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path.endsWith("/allot"))?.body).toEqual({
        office_code: "HEALTH",
        officer_user_id: null,
      }),
    );
  });

  it("a 409 already_claimed shows its message and re-reads the list and the counts", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1)], total: 1 },
      "POST /cases/ASLMS-GOA-CASE-2026-000001/claim": json(409, {
        detail: { code: "already_claimed", message: "EDU already holds this case" },
      }),
    });
    renderWithClient(<InboxFrame tab="recommended" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Claim" }));
    const before = {
      list: api.calls.filter((c) => c.path.startsWith("/inbox/recommended")).length,
      counts: api.calls.filter((c) => c.path.startsWith("/inbox/counts")).length,
    };
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Claim" }));
    expect(await screen.findByText("Your department already holds this case.")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.calls.filter((c) => c.path.startsWith("/inbox/recommended")).length).toBeGreaterThan(before.list);
      expect(api.calls.filter((c) => c.path.startsWith("/inbox/counts")).length).toBeGreaterThan(before.counts);
    });
  });
});

describe("Transfers and no release", () => {
  it("In offers Accept / Decline only with cases.transfer_decide", async () => {
    const fns = ADMIN_FNS.filter((f) => f !== "cases.transfer_decide");
    browserApi({
      "GET /me": admin(fns),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/transfers": { items: [transfer(1)], total: 1 },
    });
    renderWithClient(<InboxFrame tab="transfers" params={{}} />);
    expect(await screen.findByText("WP(C)/1/2026")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("In with the function offers Accept / Decline; Out offers Withdraw", async () => {
    const api = browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/transfers": (call: { url: string }) =>
        call.url.includes("direction=out")
          ? { items: [transfer(2, { from_office_code: "EDU", to_office_code: "FIN" })], total: 1 }
          : { items: [transfer(1)], total: 1 },
      "POST /transfers/t-1/accept": {},
    });
    const { unmount } = renderWithClient(<InboxFrame tab="transfers" params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Accept" }));
    expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("dialog", { name: "Accept the transfer" })).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "/transfers/t-1/accept")).toBe(true));
    unmount();
    renderWithClient(<InboxFrame tab="transfers" params={{ direction: "out" }} />);
    expect(await screen.findByRole("button", { name: "Withdraw" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("no row on any tab offers a release or return to the pool", async () => {
    browserApi({
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/claimed": {
        items: [
          {
            id: "o-1",
            case: summary(1),
            office_code: "EDU",
            role: "primary",
            status: "active",
            unit: { code: "EDU-DSE", name: "Secondary Education" },
            officer: { id: "u-7", full_name: "Officer One" },
            claimed_at: "2026-10-01T10:00:00Z",
            allotted_at: null,
            released_at: null,
            release_reason: null,
          },
        ],
        total: 1,
      },
    });
    renderWithClient(<InboxFrame tab="claimed" params={{}} />);
    const row = (await screen.findByText("WP(C)/1/2026")).closest("tr")!;
    expect(within(row).getByText("Officer One")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Allot" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /release|return|unclaim|stop watching/i })).toBeNull();
  });
});

describe("the filter bar on the inbox (portal-filters)", () => {
  function inboxRoutes(extra: Record<string, unknown> = {}) {
    return {
      "GET /me": admin(),
      "GET /inbox/counts": { departments: [block("EDU")] },
      "GET /inbox/recommended": { items: [rec(1), rec(2)], total: 2 },
      "GET /inbox/claimed": { items: [], total: 0 },
      "GET /inbox/pool": { items: [], total: 0 },
      "GET /inbox/transfers": { items: [], total: 0 },
      "GET /custody/recipients": DEPARTMENTS,
      ...extra,
    };
  }

  const urlOf = (calls: { path: string }[], prefix: string) => calls.filter((c) => c.path.startsWith(prefix)).at(-1)?.path ?? "";

  it("Recommended sends the shared filters with the API names and never owner", async () => {
    const api = browserApi(inboxRoutes());
    renderWithClient(
      <InboxFrame
        tab="recommended"
        params={{ q: "ram kumar", year: "2025", court_no: "3", bench: "SAIKIA", case_status: "pending", case_type: "WP(C)", owner: "FIN" }}
      />,
    );
    expect(await screen.findByText("2 cases match")).toBeInTheDocument();
    const url = urlOf(api.calls, "/inbox/recommended");
    for (const part of ["office=EDU", "q=ram+kumar", "year=2025", "court_no=3", "bench=SAIKIA", "case_status=pending", "case_type=WP%28C%29"]) {
      expect(url).toContain(part);
    }
    expect(url).not.toContain("owner=");
  });

  it("the tab badges stay the unfiltered counts", async () => {
    const api = browserApi(inboxRoutes());
    renderWithClient(<InboxFrame tab="recommended" params={{ year: "2025", listed: "d7" }} />);
    const tabs = await screen.findByRole("navigation", { name: "Inbox sections" });
    expect(within(tabs).getByRole("link", { name: "Recommended (3)" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path.startsWith("/inbox/counts")).every((c) => !c.path.includes("year="))).toBe(true);
    await waitFor(() => expect(urlOf(api.calls, "/inbox/recommended")).toContain("listed_from="));
  });

  it("Claimed sends the cause-list range; Disposed has no next-hearing filter", async () => {
    const api = browserApi(inboxRoutes());
    const { unmount } = renderWithClient(
      <InboxFrame tab="claimed" params={{ listed_from: "2026-10-01", listed_to: "2026-10-07", next: "n7" }} />,
    );
    await screen.findByText("0 cases match");
    let url = urlOf(api.calls, "/inbox/claimed");
    expect(url).toContain("case_state=active");
    expect(url).toContain("listed_from=2026-10-01");
    expect(url).toContain("listed_to=2026-10-07");
    expect(url).toContain("next_from=");
    unmount();
    renderWithClient(<InboxFrame tab="claimed" params={{ case_state: "disposed", next: "n7", year: "2025" }} />);
    await waitFor(() => expect(urlOf(api.calls, "/inbox/claimed")).toContain("case_state=disposed"));
    url = urlOf(api.calls, "/inbox/claimed");
    expect(url).toContain("year=2025");
    expect(url).not.toContain("next_from");
    expect(screen.queryByLabelText("Next hearing")).toBeNull();
  });

  it("the pool sends scored_for and reads an old status link as case_status", async () => {
    resetNav("/inbox/pool");
    const api = browserApi(inboxRoutes());
    renderWithClient(<InboxFrame tab="pool" params={{ status: "disposed", scored_for: "FIN", min_score: "0.5" }} />);
    await screen.findByText("0 cases match");
    const url = urlOf(api.calls, "/inbox/pool");
    expect(url).toContain("case_status=disposed");
    expect(url).toContain("scored_for=FIN");
    expect(url).toContain("min_score=0.5");
    expect(url).not.toMatch(/[?&]status=/);
    expect(screen.getByText("Status: Disposed")).toBeInTheDocument();
    expect(screen.getByText("Matched to department: FIN")).toBeInTheDocument();
    // the next apply rewrites the old key
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/pool?scored_for=FIN&min_score=0.5&case_status=disposed");
  });

  it("the pool's Found by our court search writes found_for to the query string and the request", async () => {
    resetNav("/inbox/pool");
    const api = browserApi(inboxRoutes());
    const { unmount } = renderWithClient(<InboxFrame tab="pool" params={{ found_for: "EDU" }} />);
    await screen.findByText("0 cases match");
    expect(urlOf(api.calls, "/inbox/pool")).toContain("found_for=EDU");
    expect(screen.getByText("Found by our court search: EDU")).toBeInTheDocument();
    unmount();
    renderWithClient(<InboxFrame tab="pool" params={{}} />);
    await screen.findByText("0 cases match");
    expect(urlOf(api.calls, "/inbox/pool")).not.toContain("found_for");
    await userEvent.selectOptions(screen.getByLabelText("Found by our court search"), "EDU");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/pool?found_for=EDU");
  });

  it("Transfers send the case filters and other_office next to the transfer status", async () => {
    resetNav("/inbox/transfers");
    const api = browserApi(inboxRoutes());
    renderWithClient(
      <InboxFrame tab="transfers" params={{ direction: "out", status: "requested", other_office: "FIN", year: "2025" }} />,
    );
    await screen.findByText("0 transfers match");
    const url = urlOf(api.calls, "/inbox/transfers");
    for (const part of ["direction=out", "status=requested", "other_office=FIN", "year=2025"]) expect(url).toContain(part);
    expect(url).not.toContain("case_status");
  });
});

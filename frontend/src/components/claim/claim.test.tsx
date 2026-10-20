/**
 * Case claim (design portal-ui-redesign, decisions 6, 7 and 10.4-10.6; round 2, row 102): the tabs by counts, rows
 * that open the large modal through `?case=`, the modal's tabs loaded on first open, "Why this is suggested", the
 * footer by the server's `actions` with the inline steps sending the selected department, `office_required`, the
 * 404 row facts, the collapsible orders with the PDF inline, the old inbox addresses, and the filter bar of each list
 * (the portal-filters tests moved here with Recommended, the pool and Transfers).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { Redirect } from "@/components/inbox/Redirects";
import { istDay } from "@/lib/format";
import type { Params } from "@/lib/params";
import type { ClaimTab } from "@/lib/routes";
import {
  actions,
  admin,
  ADMIN_FNS,
  block,
  caseDetail,
  membership,
  ownershipView,
  poolItem,
  rec,
  REF,
  summary,
  transfer,
} from "@/test/claimFixtures";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { ClaimFrame } from "./ClaimFrame";

const BASE = `/cases/${REF}`;

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

const PEOPLE = {
  departments: [],
  items: [
    { membership_id: "mm-1", user_id: "u-7", full_name: "Officer One", designation: "SO", office_code: "EDU", office_name: "Education", role_label: "Officer" },
  ],
  units: [{ code: "EDU-DSE", name: "Secondary Education" }],
  total: 1,
};

/** The modal's reads for case 1. */
function caseRoutes(own: unknown = ownershipView(actions())) {
  return {
    [`GET ${BASE}`]: caseDetail(),
    [`GET ${BASE}/ownership`]: own,
    [`GET ${BASE}/parties`]: { parties: [{ name: "RAM KUMAR", party_no: 1, role: "petitioner", address: null, has_legal_heir: null, is_current: true }], advocates: [] },
    [`GET ${BASE}/orders`]: {
      items: [
        {
          id: "o-1",
          order_no: "3",
          order_date: "2026-09-25",
          kind: "interim",
          order_details: "Issue notice",
          order_judge_name: "X",
          download_status: "stored",
          document_id: "d-1",
          date_judgement_pronounced: null,
          date_judgement_reserved: null,
          is_reportable: null,
        },
        {
          id: "o-2",
          order_no: "2",
          order_date: "2026-08-01",
          kind: "interim",
          order_details: null,
          order_judge_name: null,
          download_status: "not_published",
          document_id: null,
          date_judgement_pronounced: null,
          date_judgement_reserved: null,
          is_reportable: null,
        },
      ],
      total: 2,
    },
    [`GET ${BASE}/links`]: { items: [{ direction: "out", kind: "connected", case_no_text: "WA/5/2026", cnr: null, filing_number_text: null, source: "napix", case: summary(5), visible: true }] },
    [`GET ${BASE}/hearings`]: { items: [], total: 0 },
    [`GET ${BASE}/listings`]: { items: [], total: 0 },
  };
}

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /me": admin(),
    "GET /inbox/counts": { departments: [block("EDU")] },
    "GET /inbox/recommended": { items: [rec(1), rec(2, { score: 0.912, band: "high" })], total: 2 },
    "GET /inbox/pool": { items: [poolItem(1)], total: 1 },
    "GET /inbox/transfers": { items: [transfer(1)], total: 1 },
    "GET /custody/recipients": (call: BrowserCall) => (call.url.includes("department=") ? PEOPLE : DEPARTMENTS),
    ...caseRoutes(),
    ...extra,
  };
}

const posts = (calls: BrowserCall[]) => calls.filter((c) => c.method === "POST");

/** ClaimFrame whose query string follows the (stand-in) router, as the real page's would. */
function Routed({ tab, initial }: { tab: ClaimTab; initial: Params }) {
  const [params, setParams] = useState<Params>(initial);
  useEffect(() => {
    const follow = (url: string) => setParams(Object.fromEntries(new URLSearchParams(url.split("?")[1] ?? "")));
    nav.push.mockImplementation(follow);
    nav.replace.mockImplementation(follow);
  }, []);
  return <ClaimFrame tab={tab} params={params} />;
}

beforeEach(() => {
  resetNav("/claim/recommended");
});

describe("tabs and rows", () => {
  it("shows the tabs by counts, with the badge counts; a null count hides its tab", async () => {
    browserApi(routes({ "GET /inbox/counts": { departments: [block("EDU", { transfers_in_open: null })] } }));
    renderWithClient(<ClaimFrame tab="recommended" params={{}} />);
    const tabs = await screen.findByRole("navigation", { name: "Case claim sections" });
    expect(within(tabs).getByRole("link", { name: /Recommended.*\(3\)/ })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Unclaimed pool" })).toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: /Transfers to us/ })).toBeNull();
    expect(screen.getByText(/Nothing is assigned automatically/)).toBeInTheDocument();
  });

  it("the page has at most one primary button (decision 16)", async () => {
    browserApi(routes());
    const { container } = renderWithClient(<ClaimFrame tab="recommended" params={{}} />);
    await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" });
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("rows carry no action buttons or signal chips and show the API's band label", async () => {
    browserApi(routes());
    renderWithClient(<ClaimFrame tab="recommended" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" });
    expect(within(row).getByText("Possible · 0.849")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: "Open details of WP(C)/2/2026" })).getByText("Strong · 0.912")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Claim" })).toBeNull();
    expect(screen.queryByText("Code: SC, EDU")).toBeNull();
  });

  it("a row click opens the modal through ?case=, and Close (Back) takes it away", async () => {
    browserApi(routes());
    const { unmount } = renderWithClient(<ClaimFrame tab="recommended" params={{ band: "medium" }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" }));
    expect(nav.push).toHaveBeenCalledWith(`/claim/recommended?band=medium&case=${REF}`);
    unmount();
    renderWithClient(<ClaimFrame tab="recommended" params={{ band: "medium", case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(within(dialog).getAllByRole("button", { name: "Close" })[0]!);
    expect(nav.replace).toHaveBeenCalledWith("/claim/recommended?band=medium");
  });

  it("Enter on a focused row opens it", async () => {
    browserApi(routes());
    renderWithClient(<ClaimFrame tab="recommended" params={{}} />);
    const row = await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" });
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(nav.push).toHaveBeenCalledWith(`/claim/recommended?case=${REF}`);
  });
});

describe("the details modal", () => {
  it("shows the facts, loads each tab on first open, and the Why box lists each signal", async () => {
    const view = ownershipView(actions(), { recommendations: [rec(1)] });
    const api = browserApi(routes(caseRoutes(view)));
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    expect(await within(dialog).findByText("Suggested for your department · cause list of 25 Sep 2026")).toBeInTheDocument();
    expect(within(dialog).getByText("Not claimed")).toBeInTheDocument();
    expect(within(dialog).getByText("10 Jan 2026")).toBeInTheDocument();
    expect(within(dialog).getByText(/25 Sep 2026 · Court 3, item 41/)).toBeInTheDocument();
    // Why this is suggested: one line per signal with its contribution, the meter and the rule
    const why = within(dialog).getByRole("complementary", { name: "Why this is suggested" });
    expect(within(why).getByText("Code: SC, EDU")).toBeInTheDocument();
    expect(within(why).getByText("0.600")).toBeInTheDocument();
    expect(within(why).getByText("Linked: WP(C)/2417/2026")).toBeInTheDocument();
    expect(within(why).getByRole("meter", { name: "Match strength" })).toHaveAttribute("aria-valuenow", "0.849");
    expect(within(why).getByText(/never returns to the unclaimed pool/)).toBeInTheDocument();
    // tabs: Parties first; Orders and Linked cases load only when opened
    expect(await within(dialog).findByText("RAM KUMAR", { selector: "td" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith(`${BASE}/orders`))).toBe(false);
    expect(api.calls.some((c) => c.path.startsWith(`${BASE}/links`))).toBe(false);
    await userEvent.click(within(dialog).getByRole("tab", { name: "Orders" }));
    expect(within(dialog).getByRole("tab", { name: "Orders" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith(`${BASE}/orders`))).toBe(true));
    await userEvent.click(within(dialog).getByRole("tab", { name: "Linked cases" }));
    const link = await within(dialog).findByRole("link", { name: "WP(C)/5/2026" });
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("the modal's footer has one primary", async () => {
    browserApi(routes(caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"], dismiss: true, dismiss_departments: ["EDU"], suggest: true })))));
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await within(dialog).findByRole("button", { name: "Claim for EDU" });
    expect(dialog.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
  });

  it("the footer shows only the actions the server allows; a State-wide reader sees Close only", async () => {
    browserApi(routes(caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"] })))));
    const { unmount } = renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    expect(await within(dialog).findByRole("button", { name: "Claim for EDU" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Suggest elsewhere" })).toBeNull();
    unmount();
    const reader = makeMe(["cases.view_scope", "cases.view_all"], "state_oversight", { memberships: [] });
    browserApi(
      routes({
        "GET /me": reader,
        "GET /inbox/counts": { departments: [block("EDU")] },
        ...caseRoutes(ownershipView(actions())),
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ department: "EDU", case: REF }} />);
    const read = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await within(read).findByText("Not claimed");
    const footerButtons = within(read)
      .getAllByRole("button")
      .filter((b) => ["Claim", "Dismiss", "Suggest elsewhere"].some((t) => b.textContent?.startsWith(t)));
    expect(footerButtons).toEqual([]);
  });

  it("Claim goes through the inline step with a note and the officer, for the selected department", async () => {
    const api = browserApi(
      routes({
        ...caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"] }), { recommendations: [rec(1, { current_owner_code: "HEALTH" })] })),
        [`POST ${BASE}/claim`]: json(201, {}),
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Claim for EDU" }));
    const step = within(dialog).getByRole("group", { name: "Claim this case" });
    // no second dialog on top
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await userEvent.type(within(step).getByLabelText("Note (optional)"), "ours");
    await waitFor(() => expect(within(step).getByRole("option", { name: /Officer One/ })).toBeInTheDocument());
    await userEvent.selectOptions(within(step).getByLabelText("Officer"), "u-7");
    await userEvent.click(within(step).getByRole("button", { name: "Claim for EDU" }));
    await waitFor(() => expect(posts(api.calls)).toHaveLength(1));
    expect(posts(api.calls)[0]!.body).toEqual({ office_code: "EDU", note: "ours", officer_user_id: "u-7" });
    // the modal closes and a notice names the action with "Open case page"
    expect(nav.replace).toHaveBeenCalledWith("/claim/recommended");
    expect(await screen.findByText("Claimed WP(C)/1/2026 for EDU.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open case page" })).toHaveAttribute("href", BASE);
  });

  it("the allot fields show only with cases.allot; Back returns to the footer", async () => {
    const fns = ADMIN_FNS.filter((f) => f !== "cases.allot");
    browserApi(routes({ "GET /me": admin(fns), ...caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"] }))) }));
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Claim for EDU" }));
    const step = within(dialog).getByRole("group", { name: "Claim this case" });
    expect(within(step).queryByLabelText("Officer")).toBeNull();
    await userEvent.click(within(step).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByRole("button", { name: "Claim for EDU" })).toBeInTheDocument();
  });

  it("Dismiss needs no reason and acts for the selected department of a two-department login", async () => {
    const two = admin(ADMIN_FNS, { memberships: [membership("EDU", ADMIN_FNS), membership("HEALTH", ADMIN_FNS, false)] });
    const api = browserApi(
      routes({
        "GET /me": two,
        "GET /inbox/counts": { departments: [block("EDU"), block("HEALTH")] },
        ...caseRoutes(ownershipView(actions({ dismiss: true, dismiss_departments: ["EDU", "HEALTH"] }))),
        [`POST ${BASE}/dismiss`]: {},
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ department: "HEALTH", case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Dismiss" }));
    const step = within(dialog).getByRole("group", { name: "Dismiss this recommendation" });
    await userEvent.click(within(step).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts(api.calls)[0]?.body).toEqual({ office_code: "HEALTH" }));
  });

  it("Suggest needs a target and a reason, leaves out the owner and sends the selected department as from_office_code", async () => {
    const api = browserApi(
      routes({
        ...caseRoutes(
          ownershipView(actions({ suggest: true, suggest_departments: ["EDU"] }), {
            recommendations: [rec(1, { current_owner_code: "FIN" })],
          }),
        ),
        [`POST ${BASE}/suggest`]: {},
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Suggest elsewhere" }));
    const step = within(dialog).getByRole("group", { name: "Suggest another department" });
    const target = within(step).getByLabelText("Department");
    await waitFor(() => expect(within(target).getByRole("option", { name: /^HEALTH/ })).toBeInTheDocument());
    expect(within(target).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a department", "HEALTH — Health"]);
    await userEvent.selectOptions(target, "HEALTH");
    await userEvent.click(within(step).getByRole("button", { name: "Confirm" }));
    expect(within(step).getByText("A reason is required.")).toBeInTheDocument();
    expect(posts(api.calls)).toHaveLength(0);
    await userEvent.type(within(step).getByLabelText("Reason (required)"), "health matter");
    await userEvent.click(within(step).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(posts(api.calls)[0]?.body).toEqual({ office_code: "HEALTH", reason: "health matter", from_office_code: "EDU" }),
    );
  });

  it("an office_required answer opens the department choice", async () => {
    const api = browserApi(
      routes({
        ...caseRoutes(ownershipView(actions({ claim: true, claim_departments: null }))),
        [`POST ${BASE}/claim`]: (call: BrowserCall) =>
          (call.body as { office_code?: string }).office_code === "HEALTH"
            ? json(201, {})
            : json(400, { detail: { code: "office_required", message: "choose", candidates: ["EDU", "HEALTH"] } }),
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Claim for EDU" }));
    const step = within(dialog).getByRole("group", { name: "Claim this case" });
    await userEvent.click(within(step).getByRole("button", { name: "Claim for EDU" }));
    const select = await within(step).findByLabelText("Claim for");
    await userEvent.selectOptions(select, "HEALTH");
    await userEvent.click(within(step).getByRole("button", { name: "Claim for HEALTH" }));
    await waitFor(() => expect(posts(api.calls).at(-1)?.body).toMatchObject({ office_code: "HEALTH" }));
  });

  it("a 409 already_claimed shows its message, stays open and re-reads the list and the counts", async () => {
    const api = browserApi(
      routes({
        ...caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"] }))),
        [`POST ${BASE}/claim`]: json(409, { detail: { code: "already_claimed", message: "EDU already holds this case" } }),
      }),
    );
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Claim for EDU" }));
    const before = {
      list: api.calls.filter((c) => c.path.startsWith("/inbox/recommended")).length,
      counts: api.calls.filter((c) => c.path.startsWith("/inbox/counts")).length,
    };
    await userEvent.click(within(within(dialog).getByRole("group", { name: "Claim this case" })).getByRole("button", { name: "Claim for EDU" }));
    expect(await within(dialog).findByText("Your department already holds this case.")).toBeInTheDocument();
    await waitFor(() => {
      expect(api.calls.filter((c) => c.path.startsWith("/inbox/recommended")).length).toBeGreaterThan(before.list);
      expect(api.calls.filter((c) => c.path.startsWith("/inbox/counts")).length).toBeGreaterThan(before.counts);
    });
  });

  it("the pool's Why box shows the best score, its department and who dismissed it", async () => {
    resetNav("/claim/pool");
    browserApi(routes({ ...caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"] }))) }));
    renderWithClient(<ClaimFrame tab="pool" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" }));
    expect(nav.push).toHaveBeenCalledWith(`/claim/pool?case=${REF}`);
  });
});

describe("Transfers to us", () => {
  it("defaults to In with status requested; the modal's footer has Decline and the primary Accept transfer", async () => {
    resetNav("/claim/transfers");
    const t = transfer(1);
    const api = browserApi(
      routes({
        ...caseRoutes(ownershipView(actions({ decide_transfer: true }), { open_transfer: t })),
        "POST /transfers/t-1/accept": {},
        "POST /transfers/t-1/decline": {},
      }),
    );
    renderWithClient(<ClaimFrame tab="transfers" params={{ case: REF }} />);
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/inbox/transfers"))).toBe(true));
    const url = api.calls.find((c) => c.path.startsWith("/inbox/transfers"))!.path;
    expect(url).toContain("direction=in");
    expect(url).toContain("status=requested");
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    expect(await within(dialog).findByText("Transfer requested by HEALTH")).toBeInTheDocument();
    await userEvent.click(await within(dialog).findByRole("button", { name: "Accept transfer" }));
    const step = within(dialog).getByRole("group", { name: "Accept the transfer" });
    await userEvent.type(within(step).getByLabelText(/Note/), "agreed");
    await userEvent.click(within(step).getByRole("button", { name: "Accept transfer" }));
    await waitFor(() => expect(posts(api.calls)[0]?.path).toBe("/transfers/t-1/accept"));
    expect(posts(api.calls)[0]!.body).toEqual({ note: "agreed" });
    expect(await screen.findByText("Accepted the transfer of WP(C)/1/2026.")).toBeInTheDocument();
  });

  it("Decline goes through its step; without decide_transfer there is no Accept", async () => {
    resetNav("/claim/transfers");
    const t = transfer(1);
    const api = browserApi(
      routes({ ...caseRoutes(ownershipView(actions({ decide_transfer: true }), { open_transfer: t })), "POST /transfers/t-1/decline": {} }),
    );
    const { unmount } = renderWithClient(<ClaimFrame tab="transfers" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Decline" }));
    await userEvent.click(within(within(dialog).getByRole("group", { name: "Decline the transfer" })).getByRole("button", { name: "Decline" }));
    await waitFor(() => expect(posts(api.calls)[0]?.path).toBe("/transfers/t-1/decline"));
    unmount();
    browserApi(routes(caseRoutes(ownershipView(actions(), { open_transfer: t }))));
    renderWithClient(<ClaimFrame tab="transfers" params={{ case: REF }} />);
    const read = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await within(read).findByText("Transfer requested by HEALTH");
    expect(within(read).queryByRole("button", { name: "Accept transfer" })).toBeNull();
  });

  it("From us keeps Withdraw reachable in the modal", async () => {
    resetNav("/claim/transfers");
    const t = transfer(2, { from_office_code: "EDU", to_office_code: "FIN", case: summary(1) });
    const api = browserApi(
      routes({
        "GET /inbox/transfers": { items: [t], total: 1 },
        ...caseRoutes(ownershipView(actions({ withdraw_transfer: true }), { open_transfer: t })),
        "POST /transfers/t-2/withdraw": {},
      }),
    );
    renderWithClient(<ClaimFrame tab="transfers" params={{ direction: "out", case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Withdraw" }));
    await userEvent.click(within(within(dialog).getByRole("group", { name: /Withdraw/ })).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(posts(api.calls)[0]?.path).toBe("/transfers/t-2/withdraw"));
    expect(api.calls.find((c) => c.path.startsWith("/inbox/transfers"))!.path).toContain("direction=out");
  });

  it("a case the caller cannot open (404) shows the row's own facts only", async () => {
    resetNav("/claim/transfers");
    browserApi(
      routes({
        [`GET ${BASE}`]: json(404, { detail: "no such case" }),
        [`GET ${BASE}/ownership`]: json(404, { detail: "no such case" }),
      }),
    );
    renderWithClient(<ClaimFrame tab="transfers" params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" }));
    expect(nav.push).toHaveBeenCalledWith(`/claim/transfers?case=${REF}`);
  });

  it("the 404 modal opened from the row: facts, the reason, who asked, and no tabs", async () => {
    resetNav("/claim/transfers");
    const api = browserApi(
      routes({
        [`GET ${BASE}`]: json(404, { detail: "no such case" }),
        "POST /transfers/t-1/accept": {},
      }),
    );
    renderWithClient(<Routed tab="transfers" initial={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Open details of WP(C)/1/2026" }));
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    expect(await within(dialog).findByText("The full case opens after you accept.")).toBeInTheDocument();
    expect(within(dialog).getByText("theirs")).toBeInTheDocument();
    expect(within(dialog).getByText(/Requested by Health Admin/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("tablist")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Accept transfer" }));
    await userEvent.click(within(within(dialog).getByRole("group", { name: "Accept the transfer" })).getByRole("button", { name: "Accept transfer" }));
    await waitFor(() => expect(posts(api.calls)[0]?.path).toBe("/transfers/t-1/accept"));
  });
});

describe("orders in the modal", () => {
  it("an order expands, mounts the PDF frame once, and shows Print and Download by function", async () => {
    browserApi(routes());
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(within(dialog).getByRole("tab", { name: "Orders" }));
    const row = await within(dialog).findByRole("button", { name: /Issue notice/ });
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(dialog.querySelector("iframe")).toBeNull();
    await userEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    const frame = dialog.querySelector("iframe")!;
    expect(frame.getAttribute("src")).toBe(`/api/backend${BASE}/orders/o-1/file?disposition=inline`);
    expect(within(dialog).getByRole("link", { name: "Print" })).toHaveAttribute("target", "_blank");
    expect(within(dialog).getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      `/api/backend${BASE}/orders/o-1/file?disposition=attachment`,
    );
    // collapse and expand again: the same frame, never mounted twice
    await userEvent.click(row);
    await userEvent.click(row);
    expect(dialog.querySelectorAll("iframe")).toHaveLength(1);
    expect(dialog.querySelector("iframe")).toBe(frame);
    // an order not stored says so
    await userEvent.click(within(dialog).getByRole("button", { name: /01 Aug 2026|1 Aug 2026/ }));
    expect(within(dialog).getByText(/not yet published/i)).toBeInTheDocument();
  });

  it("without documents.download there is no Download", async () => {
    const fns = ADMIN_FNS.filter((f) => f !== "documents.download");
    browserApi(routes({ "GET /me": admin(fns) }));
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await userEvent.click(within(dialog).getByRole("tab", { name: "Orders" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: /Issue notice/ }));
    expect(within(dialog).getByRole("link", { name: "Print" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("link", { name: "Download PDF" })).toBeNull();
  });
});

describe("old addresses and the filter bars", () => {
  it("the old /inbox/recommended?band=high lands on /claim/recommended?band=high", async () => {
    resetNav("/inbox/recommended");
    renderWithClient(<Redirect to="/claim/recommended" params={{ band: "high" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/claim/recommended?band=high"));
  });

  it("the Strong chip and the cause-list filter write the query string; Recommended never sends owner", async () => {
    const api = browserApi(routes());
    renderWithClient(
      <ClaimFrame
        tab="recommended"
        params={{ q: "ram kumar", year: "2025", court_no: "3", bench: "SAIKIA", case_status: "pending", case_type: "WP(C)", owner: "FIN", listed: "today" }}
      />,
    );
    expect(await screen.findByText("2 cases match")).toBeInTheDocument();
    const url = api.calls.filter((c) => c.path.startsWith("/inbox/recommended")).at(-1)!.path;
    const today = istDay();
    for (const part of ["office=EDU", "q=ram+kumar", "year=2025", "court_no=3", "bench=SAIKIA", "case_status=pending", `listed_from=${today}`]) {
      expect(url).toContain(part);
    }
    expect(url).not.toContain("owner=");
    await userEvent.click(screen.getByRole("button", { name: "Strong" }));
    expect(nav.replace).toHaveBeenCalledWith(expect.stringContaining("band=high"));
  });

  it("the pool sends scored_for and reads an old status link as case_status; found_for writes the query string", async () => {
    resetNav("/claim/pool");
    const api = browserApi(routes({ "GET /inbox/pool": { items: [], total: 0 } }));
    renderWithClient(<ClaimFrame tab="pool" params={{ status: "disposed", scored_for: "FIN", min_score: "0.5" }} />);
    await screen.findByText("0 cases match");
    const url = api.calls.filter((c) => c.path.startsWith("/inbox/pool")).at(-1)!.path;
    expect(url).toContain("case_status=disposed");
    expect(url).toContain("scored_for=FIN");
    expect(url).toContain("min_score=0.5");
    expect(url).not.toMatch(/[?&]status=/);
    expect(screen.getByText("Status: Disposed")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Found by our court search"), "EDU");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    const written = nav.replace.mock.calls.at(-1)![0] as string;
    expect(written.startsWith("/claim/pool?")).toBe(true);
    for (const part of ["scored_for=FIN", "min_score=0.5", "found_for=EDU", "case_status=disposed"]) expect(written).toContain(part);
    expect(written).not.toMatch(/[?&]status=/);
  });

  it("Transfers send the case filters and other_office next to the transfer status", async () => {
    resetNav("/claim/transfers");
    const api = browserApi(routes({ "GET /inbox/transfers": { items: [], total: 0 } }));
    renderWithClient(<ClaimFrame tab="transfers" params={{ direction: "out", status: "requested", other_office: "FIN", year: "2025" }} />);
    await screen.findByText("0 transfers match");
    const url = api.calls.filter((c) => c.path.startsWith("/inbox/transfers")).at(-1)!.path;
    for (const part of ["direction=out", "status=requested", "other_office=FIN", "year=2025"]) expect(url).toContain(part);
    expect(url).not.toContain("case_status");
  });

  it("no screen of Case claim offers a release or return to the pool", async () => {
    browserApi(routes(caseRoutes(ownershipView(actions({ claim: true, claim_departments: ["EDU"], dismiss: true, dismiss_departments: ["EDU"], suggest: true })))));
    renderWithClient(<ClaimFrame tab="recommended" params={{ case: REF }} />);
    const dialog = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    await within(dialog).findByRole("button", { name: "Claim for EDU" });
    expect(screen.queryByRole("button", { name: /release|return|unclaim|stop watching/i })).toBeNull();
  });
});

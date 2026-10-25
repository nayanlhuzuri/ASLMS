import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseSummary, CustodyCard, CustodySummary, HeldItem, Me, SentItem } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient } from "@/test/render";

import { Held } from "./Held";
import { Sent } from "./Sent";

function summary(id: string, caseNo: string, ref = `ASLMS/GOA/CASE/2026/${id}`): CaseSummary {
  return {
    id,
    ref_no: ref,
    cnr: null,
    case_no_text: caseNo,
    is_provisional: false,
    last_listed_on: null,
    last_listing: null,
    next_hearing_date: null,
    petitioner_summary: "RAM KUMAR",
    respondent_summary: "STATE OF ASSAM",
    status: "pending",
  };
}

function card(extra: Partial<CustodyCard> = {}): CustodyCard {
  return {
    due_soon: false,
    can_recall: true,
    can_send: true,
    due_date: "2026-10-10",
    holder_office: { code: "EDU-DSE", name: "Secondary Education" },
    holder_user: { id: "u-7", full_name: "Officer One", designation: "Section Officer" },
    leg_seq_no: 2,
    overdue: true,
    overdue_days: 3,
    pending_action: "parawise_comments",
    pending_action_label: "Parawise comments",
    reason: "sent",
    remark: "please comment",
    sent_by: { name: "Edu Admin", designation: "Joint Secretary", office_code: "EDU" },
    since: "2026-10-01T10:00:00Z",
    ...extra,
  };
}

function held(items: HeldItem[]) {
  return { items, total: items.length };
}

function sentItem(
  id: string,
  caseNo: string,
  visible: boolean,
  remark: string | null = "over to you",
  extra: Partial<SentItem> = {},
): SentItem {
  return {
    case: summary(id, caseNo),
    visible,
    current: visible ? true : null,
    leg: {
      seq_no: 2,
      holder_office: { code: "HEALTH", name: "Health" },
      holder_user: { id: "u-h1", full_name: "Health Off" },
      holder_designation: "Under Secretary",
      reason: "sent",
      reason_label: "Sent",
      pending_action: "examine",
      pending_action_label: "Examine",
      due_date: "2099-11-01",
      remark,
      started_at: "2026-10-13T10:00:00Z",
      actor_name: "Anita Sharma",
      actor_designation: "Under Secretary",
      actor_office_code: "EDU",
    },
    ...extra,
  };
}

function tracker(): Me {
  return makeMe(["cases.view_scope", "custody.track"], "dept_admin", {
    memberships: [
      {
        id: "m-1",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: "Joint Secretary",
        role: "dept_admin",
        is_primary: true,
        is_active: true,
        functions: ["cases.view_scope", "custody.track"],
      },
    ],
  });
}

const SUMMARY: CustodySummary = {
  departments: [
    {
      code: "EDU",
      held: 5,
      due_soon: 2,
      overdue: 1,
      by_holder_department: [{ code: "HEALTH", held: 2, due_soon: 1, overdue: 0 }],
      by_holder: [{ office_code: "HEALTH", user_name: "Health Off", designation: "Under Secretary", held: 2, due_soon: 1, overdue: 0 }],
    },
    {
      code: "FIN",
      held: 1,
      due_soon: 0,
      overdue: 0,
      by_holder_department: [],
      by_holder: [],
    },
  ],
};

const DEPTS = { departments: [{ code: "EDU", name: "Education" }, { code: "HEALTH", name: "Health" }], items: [], units: [], total: 2 };

const headers = (table: HTMLElement) =>
  within(table)
    .getAllByRole("columnheader")
    .map((h) => h.textContent);

beforeEach(() => {
  resetNav("/inbox/working");
  sessionStorage.clear();
});

/**
 * The held and sent lists (design case-workspace-admin, decisions 17-20), now tabs of the Case inbox (design
 * case-inbox-merge, decisions 7 and 8): Working on's Show "With me" and "With my offices", Sent by me and Pending action.
 */
describe("the custody lists of the Case inbox (case-workspace-admin, decisions 17-20)", () => {
  it("Show: With me calls scope=me; With my offices sends scope=office at once, through the URL; All leaves the list", async () => {
    const api = browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    const { unmount } = renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    expect(await screen.findByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-c1");
    const call = api.calls.find((c) => c.path.startsWith("/custody/held"))!;
    expect(call.path).toContain("scope=me");
    expect(call.path).not.toContain("overdue");
    const show = screen.getByRole("radiogroup", { name: "Show" });
    expect(within(show).getAllByRole("radio").map((r) => r.textContent)).toEqual(["All", "With me", "With my offices"]);
    expect(within(show).getByRole("radio", { name: "With me" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(show).getByRole("radio", { name: "With my offices" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?held=offices");
    await userEvent.click(within(show).getByRole("radio", { name: "All" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/inbox/working");
    unmount();
    renderWithClient(<Held tab="with-me" params={{ held: "offices" }} />);
    await waitFor(() => expect(api.calls.some((c) => c.path.includes("scope=office"))).toBe(true));
    expect(await screen.findByRole("table", { name: "Cases with my offices" })).toBeInTheDocument();
    expect(within(screen.getByRole("radiogroup", { name: "Show" })).getByRole("radio", { name: "With my offices" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("Cases with me: the lead badge, case and parties, action needed, due by, From and the chevron", async () => {
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    const table = await screen.findByRole("table", { name: "Cases with me" });
    expect(headers(table)).toEqual(["Status", "Case and parties", "Action needed", "Due by", "From", "Case details"]);
    const cells = within(table).getAllByRole("cell");
    expect(cells[0]!.querySelector("[data-lead='lead']")).not.toBeNull();
    expect(within(cells[0]!).getByText("Overdue")).toBeInTheDocument();
    expect(within(table).getByText("RAM KUMAR vs STATE OF ASSAM")).toBeInTheDocument();
    expect(within(table).getByText("Parawise comments")).toBeInTheDocument();
    expect(within(table).getByText("10 Oct 2026")).toBeInTheDocument();
    // From: the sender's designation and office, the name as the title (decision 13)
    expect(within(table).getByText("Joint Secretary, EDU")).toHaveAttribute("title", "Edu Admin");
  });

  it("Pending action: With the holder, the tracking summary and 'Department it is with'", async () => {
    resetNav("/inbox/pending");
    const api = browserApi({
      "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card({ overdue: false, overdue_days: 0, due_date: null }) }]),
      "GET /custody/summary": SUMMARY,
      "GET /custody/recipients": DEPTS,
    });
    const { unmount } = renderWithClient(<Held tab="pending" params={{}} />);
    const edu = await screen.findByRole("region", { name: "Tracking summary: EDU" });
    expect(within(edu).getByRole("table", { name: "By the department it is with" })).toBeInTheDocument();
    expect(within(edu).getByRole("table", { name: "By who has them" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tracking summary: FIN" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Cases of my department waiting on someone" });
    expect(headers(table)).toEqual(["Status", "Case and parties", "Action needed", "Due by", "With", "Case details"]);
    expect(within(table).getByText("Section Officer, Secondary Education")).toHaveAttribute("title", "Officer One");
    expect(within(table).getByText("Waiting")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.startsWith("/custody/held"))!.path).toContain("scope=owned");
    expect(screen.queryByRole("radiogroup", { name: "Show" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Department it is with"), "HEALTH");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/pending?holder_department=HEALTH");
    unmount();
    renderWithClient(<Held tab="pending" params={{ holder_department: "HEALTH", overdue: "true" }} />);
    await waitFor(() =>
      expect(api.calls.some((c) => c.path.includes("holder_department=HEALTH") && c.path.includes("overdue=true"))).toBe(true),
    );
  });

  it("Overdue only goes to the query string and to the API as overdue=true", async () => {
    const api = browserApi({ "GET /custody/held": held([]) });
    const { unmount } = renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    expect(await screen.findByText("No case is with you.")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Overdue only"));
    expect(nav.replace).not.toHaveBeenCalled(); // the bar applies with Apply (portal-filters, decision 9)
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/working?held=me&overdue=true");
    unmount();
    renderWithClient(<Held tab="with-me" params={{ held: "me", overdue: "true" }} />);
    await waitFor(() => expect(api.calls.some((c) => c.path.includes("overdue=true"))).toBe(true));
  });

  it("a 403 on Pending action says tracking is not among the functions", async () => {
    browserApi({
      "GET /custody/held": json(403, { detail: { code: "forbidden", message: "custody.track needed" } }),
      "GET /custody/summary": json(403, { detail: { code: "forbidden", message: "custody.track needed" } }),
      "GET /custody/recipients": DEPTS,
    });
    renderWithClient(<Held tab="pending" params={{}} />);
    const alerts = await screen.findAllByText("Tracking the pending cases of this department is not among your functions.");
    expect(alerts.length).toBeGreaterThan(0);
  });

  it("Sent by me: Sent to the leg's holder, a link only for visible cases, Recalled under the number, a muted past leg", async () => {
    const api = browserApi({
      "GET /custody/sent": {
        items: [
          sentItem("c1", "WP(C)/1/2026", true),
          sentItem("c2", "WA/2/2026", false),
          sentItem("c3", "WP(C)/3/2026", true, null, { current: false }),
          sentItem("c4", "WP(C)/4/2026", true, "taken back", {
            leg: { ...sentItem("c4", "x", true).leg, reason: "recalled", reason_label: "Recalled" },
          }),
        ],
        total: 4,
      },
    });
    renderWithClient(<Sent params={{}} />);
    const table = await screen.findByRole("table", { name: "Cases I sent or recalled" });
    expect(headers(table)).toEqual(["Status", "Case and parties", "Action needed", "Due by", "Sent to", "Case details"]);
    expect(within(table).getByRole("link", { name: "WP(C)/1/2026" })).toBeInTheDocument();
    expect(within(table).queryByRole("link", { name: "WA/2/2026" })).toBeNull();
    expect(within(table).getByText("WA/2/2026")).toBeInTheDocument();
    expect(within(table).getAllByText("Under Secretary, Health")).toHaveLength(4);
    const row = (name: string) => within(table).getByText(name).closest("tr")!;
    expect(within(row("WP(C)/1/2026")).getByText("Waiting")).toBeInTheDocument();
    // not visible: current is null, the row says nothing about where the case went
    expect(within(row("WA/2/2026")).queryByText(/Waiting|Overdue|Due soon/)).toBeNull();
    expect(row("WP(C)/3/2026").className).toMatch(/muted/i);
    expect(within(row("WP(C)/3/2026")).queryByText("Waiting")).toBeNull();
    expect(within(row("WP(C)/4/2026")).getByText("Recalled")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.startsWith("/custody/sent"))!.path).toBe("/custody/sent?limit=50&offset=0");
  });

  it("no list offers an action button", async () => {
    browserApi({
      "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card({ remark: null }) }]),
      "GET /custody/sent": { items: [sentItem("c1", "WP(C)/1/2026", true, null)], total: 1 },
    });
    renderWithClient(
      <>
        <Held tab="with-me" params={{ held: "me" }} />
        <Sent params={{}} />
      </>,
    );
    await screen.findByRole("table", { name: "Cases with me" });
    await screen.findByRole("table", { name: "Cases I sent or recalled" });
    for (const table of screen.getAllByRole("table")) expect(within(table).queryAllByRole("button")).toHaveLength(0);
  });

  it("a row opens the side panel with the row's facts and the full remark; Close closes it (decision 20)", async () => {
    const long = "Line one of the remark\nline two of the remark\nline three of the remark";
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card({ remark: long }) }]) });
    renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    expect(screen.queryByText(/line three of the remark/)).toBeNull();
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/1/2026" }));
    const panel = await screen.findByRole("dialog", { name: "Case details" });
    expect(within(panel).getByText(/line three of the remark/)).toBeInTheDocument();
    expect(within(panel).getByText("Section Officer, Secondary Education")).toBeInTheDocument();
    expect(within(panel).getByText("Joint Secretary, EDU")).toBeInTheDocument();
    for (const label of ["With", "Action needed", "Since", "Due by", "From"]) expect(within(panel).getByText(label)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open case page" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-c1");
    expect(panel.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("rows become cards on phones: every cell carries its label, the lead badge sits in the fixed column", async () => {
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    const { container } = renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    const table = await screen.findByRole("table", { name: "Cases with me" });
    expectDataTable(table);
    const cells = within(table).getAllByRole("cell");
    expect(cells[0]!.querySelector("[data-lead='lead']")).not.toBeNull();
    expect(cells[0]).toHaveAttribute("data-label", "Status");
    expect(cells.find((c) => c.getAttribute("data-label") === "From")).toBeDefined();
    // no primary but the filter bar's Apply (one primary per page)
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("a link inside a row opens the case page, not the panel", async () => {
    browserApi({ "GET /custody/held": held([{ case: summary("c1", "WP(C)/1/2026"), card: card() }]) });
    renderWithClient(<Held tab="with-me" params={{ held: "me" }} />);
    const link = await screen.findByRole("link", { name: "WP(C)/1/2026" });
    link.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(link);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a Sent row the caller cannot open shows the panel without Open case page", async () => {
    browserApi({ "GET /custody/sent": { items: [sentItem("c2", "WA/2/2026", false, "for your opinion")], total: 1 } });
    renderWithClient(<Sent params={{}} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WA/2/2026" }));
    const panel = await screen.findByRole("dialog", { name: "Case details" });
    expect(within(panel).getByText("for your opinion")).toBeInTheDocument();
    expect(within(panel).queryByRole("link")).toBeNull();
  });
});

describe("the filter bar on the Cases list (portal-filters)", () => {
  const SHARED = { q: "ram kumar", year: "2025", court_no: "3", bench: "SAIKIA", owner: "EDU", next: "n7" };

  it("each list sends the shared filters and owner", async () => {
    for (const [tab, params, scope] of [
      ["with-me", {}, "me"],
      ["with-me", { held: "offices" }, "office"],
      ["pending", {}, "owned"],
    ] as const) {
      const api = browserApi({
        "GET /me": tracker(),
        "GET /custody/held": held([]),
        "GET /custody/summary": SUMMARY,
        "GET /custody/recipients": DEPTS,
      });
      const { unmount } = renderWithClient(<Held tab={tab} params={{ ...SHARED, ...params, overdue: "true" }} />);
      await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/custody/held"))).toBe(true));
      const url = api.calls.find((c) => c.path.startsWith("/custody/held"))!.path;
      for (const part of [`scope=${scope}`, "overdue=true", "q=ram+kumar", "year=2025", "court_no=3", "bench=SAIKIA", "owner=EDU", "next_from="]) {
        expect(url, scope).toContain(part);
      }
      unmount();
    }
    const api = browserApi({ "GET /custody/sent": { items: [], total: 0 }, "GET /custody/recipients": DEPTS });
    renderWithClient(<Sent params={SHARED} />);
    await screen.findByText("0 cases match");
    const url = api.calls.find((c) => c.path.startsWith("/custody/sent"))!.path;
    for (const part of ["q=ram+kumar", "year=2025", "owner=EDU", "next_to="]) expect(url).toContain(part);
  });

  it("Pending action offers only the tracked departments as owner", async () => {
    resetNav("/inbox/pending");
    browserApi({
      "GET /me": tracker(),
      "GET /custody/held": held([]),
      "GET /custody/summary": SUMMARY,
      "GET /custody/recipients": DEPTS,
    });
    renderWithClient(<Held tab="pending" params={{ owner: "EDU" }} />);
    const owner = await screen.findByLabelText("Department");
    await waitFor(() => expect(within(owner).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any department", "EDU"]));
    // the department it is with still offers every department
    const holder = screen.getByLabelText("Department it is with");
    await waitFor(() => expect(within(holder).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
  });

  it("Cases with me offers every department as owner", async () => {
    browserApi({ "GET /me": tracker(), "GET /custody/held": held([]), "GET /custody/recipients": DEPTS });
    renderWithClient(<Held tab="with-me" params={{ owner: "HEALTH" }} />);
    const owner = await screen.findByLabelText("Department");
    await waitFor(() => expect(within(owner).getByRole("option", { name: "HEALTH — Health" })).toBeInTheDocument());
    expect(screen.getByText("Department: HEALTH")).toBeInTheDocument();
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("TrackingSummary renders a DataTable with a primary cell", async () => {
    resetNav("/inbox/pending");
    browserApi({ "GET /custody/held": held([]), "GET /custody/summary": SUMMARY, "GET /custody/recipients": DEPTS });
    renderWithClient(<Held tab="pending" params={{}} />);
    const edu = await screen.findByRole("region", { name: "Tracking summary: EDU" });
    expectDataTable(within(edu).getByRole("table", { name: "By the department it is with" }));
    expectDataTable(within(edu).getByRole("table", { name: "By who has them" }));
  });
});

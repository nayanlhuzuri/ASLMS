import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CauselistBench, CauselistDay, CauselistEntries, CauselistEntry, Permission } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { CauseList } from "./CauseList";

const D = "2026-10-13";
const DAILY = "11111111-1111-4111-8111-111111111111";
const SUPP = "22222222-2222-4222-8222-222222222222";
const WEBSITE = "33333333-3333-4333-8333-333333333333";
const READER: Permission[] = ["cases.view_scope", "documents.view", "documents.download"];
const CLAIMER: Permission[] = [...READER, "cases.claim"];

function me(functions: Permission[]) {
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

function list(id: string, list_type: string, has_pdf = true, entries = 2) {
  return {
    id,
    list_type,
    list_type_text: list_type.toUpperCase(),
    label: null,
    napix_causelist_id: 11,
    source: "napix",
    entry_count: entries,
    entries_stored: entries,
    fetch_status: has_pdf ? "fetched" : "not_available",
    parse_status: "parsed",
    has_pdf,
    version: 1,
    superseded: false,
  };
}

const BENCHES: CauselistBench[] = [
  { bench_id: 777, label: "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA", court_nos: ["2"], source: "napix", entries: 1, lists: [list("44444444-4444-4444-8444-444444444444", "daily", true, 1)] },
  {
    bench_id: 1854,
    label: "HONOURABLE THE CHIEF JUSTICE",
    court_nos: ["10"],
    source: "napix",
    entries: 53,
    lists: [list(DAILY, "daily", true, 51), list(SUPP, "supplementary", false, 2)],
  },
  { bench_id: null, label: null, court_nos: ["5"], source: "ghc_website", entries: 1, lists: [list(WEBSITE, "daily", false, 1)] },
];

function day(extra: Partial<CauselistDay> = {}): CauselistDay {
  return {
    date: D,
    state: "held",
    queue_status: "done",
    queue_finished_at: null,
    previous_date: "2026-10-12",
    next_date: "2026-10-20",
    totals: { benches: 3, lists: 4, entries: 55 },
    benches: BENCHES,
    ...extra,
  };
}

function entry(n: number, extra: Partial<CauselistEntry> = {}): CauselistEntry {
  return {
    id: `e-${n}`,
    causelist_id: DAILY,
    list_type: "daily",
    bench_id: 1854,
    bench_label: "HONOURABLE THE CHIEF JUSTICE",
    court_no: "10",
    sr_no: n,
    printed_sr_no: String(n),
    section: "ORDERS",
    is_connected: false,
    with_text: null,
    case_no_text: `WP(C)/${n}/2025`,
    cnr: `ASHC0100000${n}2025`,
    petitioner_text: `PETITIONER ${n}`,
    respondent_text: "STATE OF ASSAM",
    pet_advocate_text: "MR. A. BORA",
    res_advocate_text: "SC, REVENUE\nMS. R. DEKA",
    counsel_codes: ["SC, REVENUE"],
    remarks: null,
    source: "pdf_parse",
    resolution_status: "resolved",
    case: {
      id: `c-${n}`,
      ref_no: `ASLMS/GHC/CASE/2026/00000${n}`,
      cnr: `ASHC0100000${n}2025`,
      case_no_text: `WP(C)/${n}/2025`,
      is_provisional: false,
      petitioner_summary: `PETITIONER ${n}`,
      respondent_summary: "STATE OF ASSAM",
      status: "pending",
      next_hearing_date: null,
      last_listed_on: null,
      last_listing: null,
    },
    visible: true,
    owner_office_code: null,
    held_by_you: null,
    in_pool: false,
    recommendations: [],
    claimable: false,
    ...extra,
  };
}

const COUNTS = { entries: 55, recommended: 4, mine: 1, claimable: 6, claimed: 12, unclaimed: 30 };

function page(items: CauselistEntry[], total = items.length): CauselistEntries {
  return { date: D, total, counts: COUNTS, items };
}

const ITEMS = [
  entry(1, { court_no: "2", bench_id: 777, bench_label: "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA", causelist_id: "l-777" }),
  entry(2, { recommendations: [{ office_code: "EDU", band: "high", score: 0.95 }], in_pool: true, claimable: true }),
  entry(3, { is_connected: true, printed_sr_no: null, with_text: "with WP(C) 2087/2025", visible: false, owner_office_code: "FIN" }),
  entry(4, { section: "FOR ADMISSION", owner_office_code: "EDU", held_by_you: "primary" }),
  entry(5, { section: "FOR ADMISSION", case: null, cnr: null, case_no_text: "WP(C)/999/2026", visible: false }),
  entry(6, { causelist_id: SUPP, list_type: "supplementary", section: "ORDERS", owner_office_code: "FIN", held_by_you: "watcher" }),
];

function routes(extra: Record<string, unknown> = {}, functions: Permission[] = CLAIMER) {
  return {
    "GET /me": me(functions),
    "GET /custody/recipients": { departments: [{ code: "EDU", name: "Education" }, { code: "FIN", name: "Finance" }], items: [], units: [], total: 0 },
    "GET /causelists/dates": { from: "2026-08-14", to: "2026-10-20", today: D, default_date: D, items: [] },
    [`GET /causelists/${D}`]: day(),
    [`GET /causelists/${D}/entries`]: page(ITEMS),
    ...extra,
  };
}

function entriesCall(api: ReturnType<typeof browserApi>) {
  const calls = api.calls.filter((c) => c.path.startsWith(`/causelists/${D}/entries`));
  return new URL(calls[calls.length - 1]!.path, "http://x").searchParams;
}

beforeEach(() => {
  resetNav("/causelist");
});

describe("the date", () => {
  it("opens on default_date and writes it to the URL", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{}} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/causelist?date=${D}`));
  });

  it("Previous Day and Next Day move by one day and drop the bench (portal-ui-polish-2, decision 24)", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854", q: "anima" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Previous Day" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/causelist?date=2026-10-12&q=anima");
    await userEvent.click(screen.getByRole("button", { name: "Next Day" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/causelist?date=2026-10-14&q=anima");
  });

  it("a day without lists offers Previous List and Next List to the API's dates", async () => {
    browserApi(routes({ [`GET /causelists/${D}`]: day({ state: "no_list", benches: [] }) }));
    renderWithClient(<CauseList params={{ date: D }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Previous List" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/causelist?date=2026-10-12");
    await userEvent.click(screen.getByRole("button", { name: "Next List" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/causelist?date=2026-10-20");
  });

  it.each([
    ["loading", "being fetched from the court"],
    ["no_list", "published no cause list"],
    ["failed", "failed"],
    ["not_loaded", "Not loaded yet"],
  ])("a %s day shows its banner", async (state, text) => {
    browserApi(routes({ [`GET /causelists/${D}`]: day({ state: state as CauselistDay["state"], benches: [] }) }));
    renderWithClient(<CauseList params={{ date: D }} />);
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("fetching a missing day", () => {
  const notLoaded = { [`GET /causelists/${D}`]: day({ state: "not_loaded", benches: [] }) };

  it("only holders of admin.napix_refetch see the button, and only on not_loaded / failed / no_list", async () => {
    browserApi(routes(notLoaded));
    renderWithClient(<CauseList params={{ date: D }} />);
    await screen.findByText(/Not loaded yet/);
    expect(screen.queryByRole("button", { name: "Fetch This Day From the Court" })).toBeNull();
  });

  it("no button on a loading day even for an operator", async () => {
    browserApi(routes({ [`GET /causelists/${D}`]: day({ state: "loading", benches: [] }) }, [...READER, "admin.napix_refetch"]));
    renderWithClient(<CauseList params={{ date: D }} />);
    await screen.findByText(/being fetched/);
    expect(screen.queryByRole("button", { name: "Fetch This Day From the Court" })).toBeNull();
  });

  it("posts the day, and a 409 already_held asks before resending with force", async () => {
    const api = browserApi(
      routes(
        {
          ...notLoaded,
          "POST /admin/napix/refetch/day": (call: { body: { force?: boolean } }) =>
            call.body.force
              ? { kind: "causelist_day", ref: D, status: "pending" }
              : json(409, { detail: { code: "already_held", message: "held", status: "skipped", lists_stored: 0 } }),
        },
        [...READER, "admin.napix_refetch"],
      ),
    );
    renderWithClient(<CauseList params={{ date: D }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Fetch This Day From the Court" }));
    const dialog = await screen.findByRole("dialog", { name: "Already Held" });
    expect(within(dialog).getByText(/published no cause list/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Fetch Anyway" }));
    expect(await screen.findByText(/Asked for/)).toBeInTheDocument();
    const posts = api.calls.filter((c) => c.method === "POST" && c.path === "/admin/napix/refetch/day");
    expect(posts.map((c) => c.body)).toEqual([{ date: D }, { date: D, force: true }]);
  });
});

describe("the bench", () => {
  it("lists the day's benches with court number, label and count; choosing one writes bench_id", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const select = await screen.findByLabelText("Bench");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All Benches",
      "Court 2 · HONOURABLE MR. JUSTICE SOUMITRA SAIKIA · 1",
      "Court 10 · HONOURABLE THE CHIEF JUSTICE · 53",
      "Court 5 · Court-wide List · 1",
    ]);
    await userEvent.selectOptions(select, "b:1854");
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&bench_id=1854`);
    await userEvent.selectOptions(select, `l:${WEBSITE}`);
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&list_id=${WEBSITE}`);
  });

  it("the chosen bench's lists offer View with documents.view and Download with documents.download", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854" }} />);
    const lists = await screen.findByRole("region", { name: "Lists of This Bench" });
    const items = within(lists).getAllByRole("listitem");
    expect(within(items[0]!).getByRole("link", { name: "View" })).toHaveAttribute(
      "href",
      `/api/backend/causelists/lists/${DAILY}/file?disposition=inline`,
    );
    expect(within(items[0]!).getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      `/api/backend/causelists/lists/${DAILY}/file?disposition=attachment`,
    );
    expect(within(items[1]!).getByText("PDF not available from the court")).toBeInTheDocument();
    expect(within(items[1]!).queryByRole("link")).toBeNull();
  });

  it("without the file functions neither View nor Download shows", async () => {
    browserApi(routes({}, ["cases.view_scope", "documents.view"]));
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854" }} />);
    const lists = await screen.findByRole("region", { name: "Lists of This Bench" });
    expect(within(lists).getAllByRole("link", { name: "View" })).toHaveLength(1);
    expect(within(lists).queryByRole("link", { name: "Download" })).toBeNull();
  });
});

describe("the entries", () => {
  it("render in API order with a heading at each court, bench, list and section change", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const table = await screen.findByRole("table", { name: "Cause-list Entries" });
    const headings = within(table)
      .getAllByRole("columnheader")
      .filter((th) => th.getAttribute("scope") === "colgroup")
      .map((th) => th.textContent);
    expect(headings).toEqual([
      "Court 2",
      "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA",
      "Daily List",
      "ORDERS",
      "Court 10",
      "HONOURABLE THE CHIEF JUSTICE",
      "Daily List",
      "ORDERS",
      "FOR ADMISSION",
      "Supplementary List",
      "ORDERS",
    ]);
    const cases = within(table)
      .getAllByText(/^WP\(C\)\/\d+\/20\d\d$/)
      .map((n) => n.textContent);
    expect(cases).toEqual(["WP(C)/1/2025", "WP(C)/2/2025", "WP(C)/3/2025", "WP(C)/4/2025", "WP(C)/999/2026", "WP(C)/6/2025"]);
  });

  it("a connected row shows 'with …' and no item number; the case links only when visible", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const connected = (await screen.findByText("with WP(C) 2087/2025")).closest("tr")!;
    expect(within(connected).queryByText("3")).toBeNull();
    expect(within(connected).queryByRole("link")).toBeNull();
    expect(within(connected).getByText("WP(C)/3/2025")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "WP(C)/2/2025" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000002");
    const noCase = screen.getByText("WP(C)/999/2026").closest("tr")!;
    expect(within(noCase).getByText("provisional")).toBeInTheDocument();
  });

  it("owner, Your department and recommendation badges", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const owned = (await screen.findByText("WP(C)/4/2025")).closest("tr")!;
    expect(within(owned).getByText("Claimed by EDU")).toBeInTheDocument();
    expect(within(owned).getByText("Your Department")).toBeInTheDocument();
    const watched = screen.getByText("WP(C)/6/2025").closest("tr")!;
    expect(within(watched).getByText("Claimed by FIN")).toBeInTheDocument();
    expect(within(watched).getByText("Your Department (Watching)")).toBeInTheDocument();
    const rec = screen.getByText("WP(C)/2/2025").closest("tr")!;
    expect(within(rec).getByText("Strong · EDU · 0.95")).toBeInTheDocument();
    expect(within(rec).getByText("Unclaimed")).toBeInTheDocument();
  });

  it("Claim shows only when claimable, reads the case's ownership, and a success re-reads the entries", async () => {
    const own = "/cases/ASLMS-GHC-CASE-2026-000002";
    const api = browserApi(
      routes({
        [`GET ${own}/ownership`]: {
          primary: null,
          watchers: [],
          recommendations: [],
          open_transfer: null,
          actions: { claim: true, claim_departments: ["EDU"] },
        },
        [`POST ${own}/claim`]: json(201, {}),
      }),
    );
    renderWithClient(<CauseList params={{ date: D }} />);
    await screen.findByRole("table", { name: "Cause-list Entries" });
    expect(screen.getAllByRole("button", { name: "Claim" })).toHaveLength(1);
    const before = api.calls.filter((c) => c.path.startsWith(`/causelists/${D}/entries`)).length;
    const row = screen.getByText("WP(C)/2/2025").closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim This Case" });
    await waitFor(() => expect(api.calls.some((c) => c.path === `${own}/ownership`)).toBe(true));
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === `${own}/claim`)?.body).toEqual({ office_code: "EDU" }),
    );
    await waitFor(() =>
      expect(api.calls.filter((c) => c.path.startsWith(`/causelists/${D}/entries`)).length).toBeGreaterThan(before),
    );
  });
});

describe("filters", () => {
  it("send q, only, list_type and court_no with their API names", async () => {
    const api = browserApi(routes());
    renderWithClient(
      <CauseList params={{ date: D, bench_id: "1854", list_type: "supplementary", court_no: "10", q: "anima", only: "claimable", offset: "200" }} />,
    );
    await screen.findByRole("table", { name: "Cause-list Entries" });
    const sent = entriesCall(api);
    expect(Object.fromEntries(sent.entries())).toEqual({
      bench_id: "1854",
      list_type: "supplementary",
      court_no: "10",
      q: "anima",
      only: "claimable",
      limit: "200",
      offset: "200",
    });
  });

  it("the summary strip's links, the Show select and the words reset the offset (portal-ui-polish-2, decision 23)", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D, offset: "200" }} />);
    expect(await screen.findByText("55 entries")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "4 recommended to you" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&only=recommended`);
    await userEvent.click(screen.getByRole("button", { name: "6 claimable" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&only=claimable`);
    await userEvent.type(screen.getByLabelText(/^Search Words/), "SC, REV");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&q=SC%2C+REV`);
  });

  it("the list type choices (under More Filters) are the day's types, and choosing one writes list_type", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "More Filters" }));
    const select = await screen.findByLabelText("List Type");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All List Types",
      "Daily List",
      "Supplementary List",
    ]);
    await userEvent.selectOptions(select, "supplementary");
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&bench_id=1854&list_type=supplementary`);
  });
});

describe("the Work list template (portal-ui-redesign, decision 26)", () => {
  it("court and item lead every entry in the fixed column; a connected entry has no item number", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const table = await screen.findByRole("table", { name: "Cause-list Entries" });
    const rows = within(table)
      .getAllByRole("row")
      .filter((r) => r.getAttribute("tabindex") === "0");
    expect(rows).toHaveLength(6);
    for (const row of rows) expect(within(row).getAllByRole("cell")[0]!.querySelector("[data-lead='lead']")).not.toBeNull();
    expect(within(rows[1]!).getAllByRole("cell")[0]).toHaveTextContent("10 · 2");
    expect(within(rows[2]!).getAllByRole("cell")[0]).toHaveTextContent("10 · —");
  });

  it("rows become cards on phones: the cells after the case carry their labels", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const row = (await screen.findByText("WP(C)/2/2025")).closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveAttribute("data-label", "Ownership");
    expect(cells[3]).toHaveAttribute("data-label", "Action");
  });

  it("a row opens the whole entry in the side panel, Close closes it; Claim in the row does not open it", async () => {
    browserApi(routes());
    const { container } = renderWithClient(<CauseList params={{ date: D }} />);
    const row = (await screen.findByText("WP(C)/2/2025")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Claim" }));
    expect(screen.queryByRole("dialog", { name: "WP(C)/2/2025" })).toBeNull();
    await userEvent.click(within(screen.getByRole("dialog", { name: "Claim This Case" })).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
    await userEvent.click(screen.getByRole("row", { name: "Details of WP(C)/4/2025" }));
    const panel = await screen.findByRole("dialog", { name: "WP(C)/4/2025" });
    expect(within(panel).getByText("MR. A. BORA")).toBeInTheDocument();
    expect(within(panel).getByText("SC, REVENUE", { selector: "span" })).toBeInTheDocument();
    expect(within(panel).getByText("FOR ADMISSION")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open Case Page" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000004");
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("an entry the caller cannot open has no Open case page in its panel", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/3/2025" }));
    const panel = await screen.findByRole("dialog", { name: "WP(C)/3/2025" });
    expect(within(panel).queryByRole("link")).toBeNull();
    expect(within(panel).getByText("with WP(C) 2087/2025")).toBeInTheDocument();
  });
});

describe("corrected lists (court-data-freshness, decision 17)", () => {
  const OLD = "55555555-5555-4555-8555-555555555555";
  const corrected = {
    ...list(DAILY, "daily", true, 51),
    version: 2,
    supersedes_id: OLD,
    corrected_at: "2026-10-12T19:05:00+05:30",
  };
  const benches: CauselistBench[] = [{ ...BENCHES[1]!, lists: [corrected] }];

  it("a corrected list carries the badge, the time received and an Earlier version link", async () => {
    browserApi(routes({ [`GET /causelists/${D}`]: day({ benches }) }));
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854" }} />);
    const lists = await screen.findByRole("region", { name: "Lists of This Bench" });
    expect(within(lists).getByText("Corrected List")).toBeInTheDocument();
    expect(within(lists).getByText(/^received /)).toBeInTheDocument();
    await userEvent.click(within(lists).getByRole("button", { name: "Earlier Version" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&list_id=${OLD}`);
  });

  it("the earlier version says it was replaced, offers its PDF and a way back to the current list", async () => {
    const earlier = { ...list(OLD, "daily", true, 4), superseded: true, superseded_at: "2026-10-12T19:05:00+05:30" };
    browserApi(
      routes({
        [`GET /causelists/${D}`]: day({ benches }),
        [`GET /causelists/${D}/entries`]: { ...page([entry(1)]), list: earlier },
      }),
    );
    renderWithClient(<CauseList params={{ date: D, list_id: OLD }} />);
    expect(await screen.findByText(/This list was replaced by a corrected list/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View" }).some((a) => a.getAttribute("href")?.includes(OLD))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Show the Current List" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&bench_id=1854`);
  });
});

describe("the date navigator (portal-ui-polish-2, decision 24)", () => {
  it("shows the weekday over the date, Lists Held from the day's lists, and No Lists on a day without", async () => {
    browserApi(routes());
    const { container, unmount } = renderWithClient(<CauseList params={{ date: D }} />);
    const hero = container.querySelector<HTMLElement>("[data-zone='hero']")!;
    expect(within(hero).getByText("Tuesday")).toBeInTheDocument();
    expect(within(hero).getByText("13 Oct 2026")).toBeInTheDocument();
    expect(await within(hero).findByText("Lists Held: 4")).toBeInTheDocument();
    unmount();
    browserApi(routes({ [`GET /causelists/${D}`]: day({ state: "no_list", benches: [], totals: { benches: 0, lists: 0, entries: 0 } }) }));
    const second = renderWithClient(<CauseList params={{ date: D }} />);
    const hero2 = second.container.querySelector<HTMLElement>("[data-zone='hero']")!;
    expect(await within(hero2).findByText("No Lists")).toBeInTheDocument();
  });

  it("Pick Date opens the browser's picker and a chosen date is written", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const input = await screen.findByTestId("pick-date");
    const showPicker = vi.fn();
    Object.defineProperty(input, "showPicker", { value: showPicker, configurable: true });
    await userEvent.click(screen.getByRole("button", { name: "Pick Date" }));
    expect(showPicker).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { value: "2026-10-09" } });
    expect(nav.replace).toHaveBeenLastCalledWith("/causelist?date=2026-10-09");
  });

  it("the Show select replaces the show-only chips and writes only", async () => {
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D }} />);
    const show = await screen.findByRole("combobox", { name: "Show" });
    expect(screen.queryByRole("button", { name: "Recommended to Me (4)" })).toBeNull();
    expect(within(show).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All Entries (55)",
      "Recommended to Me (4)",
      "Mine (1)",
      "Claimable (6)",
      "Unclaimed (30)",
      "Claimed (12)",
      "Visible to Me",
    ]);
    await userEvent.selectOptions(show, "mine");
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&only=mine`);
  });
});

describe("View Cause List (portal-ui-polish-2, decision 25)", () => {
  const ENTRIES_100 = (call: { path: string }) => {
    const sp = new URL(call.path, "http://x").searchParams;
    return sp.get("limit") === "100" ? page([ITEMS[1]!, entry(4, { owner_office_code: "EDU", held_by_you: "primary" })], 140) : page(ITEMS);
  };

  it("is disabled with All Benches, with the hint, and opens ?view=<bench>&vtab=entries once a bench is chosen", async () => {
    browserApi(routes());
    const { unmount } = renderWithClient(<CauseList params={{ date: D }} />);
    const button = await screen.findByRole("button", { name: "View Cause List" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("Choose a bench to view its list.");
    unmount();
    browserApi(routes());
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854" }} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "View Cause List" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "View Cause List" }));
    expect(nav.push).toHaveBeenLastCalledWith(`/causelist?date=${D}&bench_id=1854&view=1854&vtab=entries`);
  });

  it("shows the bench's printed entries paged by 100 with the page's badges, and Close leaves the page as it was", async () => {
    const api = browserApi(routes({ [`GET /causelists/${D}/entries`]: ENTRIES_100 }));
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854", view: "1854", vtab: "entries" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Cause List: HONOURABLE THE CHIEF JUSTICE · 13 Oct 2026" });
    expect(within(dialog).getByText("Daily List")).toBeInTheDocument();
    expect(within(dialog).getByText("Supplementary List")).toBeInTheDocument();
    const table = await within(dialog).findByRole("table", { name: "Cause-list Entries" });
    expect(within(table).getByRole("link", { name: "WP(C)/2/2025" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000002");
    expect(within(table).getByText("Strong · EDU · 0.95")).toBeInTheDocument();
    expect(within(table).getByText("Claimed by EDU")).toBeInTheDocument();
    expect(within(table).getAllByText("MR. A. BORA").length).toBeGreaterThan(0);
    // Claim stays on the page
    expect(within(dialog).queryByRole("button", { name: "Claim" })).toBeNull();
    const sent = api.calls.filter((c) => c.path.includes("limit=100"));
    expect(Object.fromEntries(new URL(sent[0]!.path, "http://x").searchParams.entries())).toEqual({
      bench_id: "1854",
      limit: "100",
      offset: "0",
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.calls.some((c) => c.path.includes("limit=100") && c.path.includes("offset=100"))).toBe(true));
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(nav.replace).toHaveBeenLastCalledWith(`/causelist?date=${D}&bench_id=1854`);
  });

  it("the Original PDF tab offers a list chooser, the inline viewer with documents.view and Download with documents.download", async () => {
    const api = browserApi(routes({ [`GET /causelists/lists/${DAILY}/file`]: {} }));
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854", view: "1854" }} />);
    const dialog = await screen.findByRole("dialog");
    const replace = vi.spyOn(window.history, "replaceState");
    await userEvent.click(within(dialog).getByRole("link", { name: "Original PDF" }));
    expect(replace).toHaveBeenLastCalledWith(window.history.state, "", `/causelist?date=${D}&bench_id=1854&view=1854&vtab=pdf`);
    const chooser = within(dialog).getByLabelText("List");
    expect(within(chooser).getAllByRole("option").map((o) => o.textContent)).toEqual(["Daily List", "Supplementary List"]);
    const frame = await waitFor(() => {
      const f = dialog.querySelector("iframe");
      expect(f).not.toBeNull();
      return f!;
    });
    expect(frame).toHaveAttribute("src", `/api/backend/causelists/lists/${DAILY}/file?disposition=inline`);
    expect(api.calls.some((c) => c.path === `/causelists/lists/${DAILY}/file?disposition=inline`)).toBe(true);
    expect(within(dialog).getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      `/api/backend/causelists/lists/${DAILY}/file?disposition=attachment`,
    );
    await userEvent.selectOptions(chooser, SUPP);
    expect(within(dialog).getByText("PDF not available from the court")).toBeInTheDocument();
    expect(dialog.querySelector("iframe")).toBeNull();
    replace.mockRestore();
  });

  it("without the documents functions the PDF tab says so; a file_missing answer shows the API's message", async () => {
    browserApi(routes({}, ["cases.view_scope"]));
    const { unmount } = renderWithClient(<CauseList params={{ date: D, bench_id: "1854", view: "1854", vtab: "pdf" }} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/needs the documents function/)).toBeInTheDocument();
    expect(dialog.querySelector("iframe")).toBeNull();
    unmount();
    browserApi(
      routes(
        {
          [`GET /causelists/lists/${DAILY}/file`]: json(404, {
            detail: { code: "file_missing", message: "The stored PDF of this list is missing." },
          }),
        },
        ["cases.view_scope", "documents.view"],
      ),
    );
    renderWithClient(<CauseList params={{ date: D, bench_id: "1854", view: "1854", vtab: "pdf" }} />);
    const second = await screen.findByRole("dialog");
    expect(await within(second).findByText("The stored PDF of this list is missing.")).toBeInTheDocument();
    expect(second.querySelector("iframe")).toBeNull();
    expect(within(second).queryByRole("link", { name: "Download" })).toBeNull();
  });
});

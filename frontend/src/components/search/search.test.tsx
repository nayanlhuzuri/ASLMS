import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CaseSearchItem, Permission } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, json, makeMe, renderWithClient } from "@/test/render";

import { Search } from "./Search";

const READER: Permission[] = ["cases.view_scope", "documents.view"];
const SEARCHER: Permission[] = ["cases.view_scope", "cases.search_court", "cases.claim"];

function item(n: number, extra: Partial<CaseSearchItem> = {}, caseExtra: Partial<CaseSearchItem["case"]> = {}): CaseSearchItem {
  return {
    case: {
      id: `c-${n}`,
      ref_no: `ASLMS/GOA/CASE/2026/00000${n}`,
      cnr: `ASHC01000${n}002026`,
      case_no_text: `WP(C)/${n}/2026`,
      is_provisional: false,
      petitioner_summary: "RAM KUMAR",
      respondent_summary: "STATE OF ASSAM",
      status: "pending",
      next_hearing_date: null,
      last_listed_on: null,
      last_listing: null,
      ...caseExtra,
    },
    visible: true,
    owner_office_code: null,
    in_pool: false,
    claimable: false,
    match: "party",
    dossier_status: "fetched",
    ...extra,
  };
}

const TYPES = [
  { case_type_code: 1, short_name: "WP(C)", full_name: "Writ Petition (Civil)", type_name: "WP(C)" },
  { case_type_code: 2, short_name: "Crl.A.", full_name: "Criminal Appeal", type_name: "CRL.A" },
];

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

beforeEach(() => {
  resetNav("/search");
});

describe("local search", () => {
  it("without words lists the caller's visible cases from GET /cases", async () => {
    const api = browserApi({
      "GET /me": me(READER),
      "GET /reference/case-types": TYPES,
      "GET /cases": { items: [item(1)], total: 1 },
    });
    renderWithClient(<Search params={{}} />);
    expect(await screen.findByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute(
      "href",
      "/cases/ASLMS-GOA-CASE-2026-000001",
    );
    expect(screen.getByRole("heading", { name: /Your cases/ })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/cases?") || c.path === "/cases")).toBe(true);
    expect(api.calls.some((c) => c.path.startsWith("/cases/search"))).toBe(false);
  });

  it("with words calls /cases/search with the filters", async () => {
    const api = browserApi({
      "GET /me": me(READER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [item(1), item(2)], total: 2 },
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR", year: "2026", case_type: "WP(C)", visible_only: "true" }} />);
    await screen.findByRole("link", { name: "WP(C)/2/2026" });
    const call = api.calls.find((c) => c.path.startsWith("/cases/search"))!;
    expect(call.url).toContain("q=RAM+KUMAR");
    expect(call.url).toContain("year=2026");
    expect(call.url).toContain("case_type=WP%28C%29");
    expect(call.url).toContain("visible_only=true");
  });

  it("case types come from /reference/case-types", async () => {
    browserApi({
      "GET /me": me(READER),
      "GET /reference/case-types": TYPES,
      "GET /cases": { items: [], total: 0 },
    });
    renderWithClient(<Search params={{}} />);
    const select = await screen.findByLabelText("Case type");
    await waitFor(() => expect(within(select).getByRole("option", { name: /Crl.A. — Criminal Appeal/ })).toBeInTheDocument());
    await userEvent.selectOptions(select, "WP(C)");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/search?case_type=WP%28C%29");
  });

  it("a row the caller cannot open is text, not a link, and offers Claim when claimable", async () => {
    browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": {
        items: [item(3, { visible: false, in_pool: true, claimable: true, dossier_status: "not_fetched" })],
        total: 1,
      },
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const text = await screen.findByText("WP(C)/3/2026");
    expect(text.closest("a")).toBeNull();
    const row = text.closest("tr")!;
    expect(within(row).getByText("In the unclaimed pool")).toBeInTheDocument();
    expect(within(row).getByText("Court details not yet fetched")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Claim" }));
    expect(screen.getByRole("dialog", { name: "Claim this case" })).toBeInTheDocument();
  });

  it("Claim on a result reads the case's ownership and offers its claim_departments", async () => {
    const own = "/cases/ASLMS-GOA-CASE-2026-000003";
    const api = browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [item(3, { visible: false, claimable: true, owner_office_code: "FIN" })], total: 1 },
      [`GET ${own}/ownership`]: {
        primary: null,
        watchers: [],
        recommendations: [],
        open_transfer: null,
        actions: { claim: true, claim_departments: ["EDU", "HEALTH"] },
      },
      [`POST ${own}/claim`]: json(201, {}),
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const row = (await screen.findByText("WP(C)/3/2026")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    const pick = await within(dialog).findByLabelText("Claim for");
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a department", "EDU", "HEALTH"]);
    await userEvent.selectOptions(pick, "HEALTH");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.path === `${own}/claim`)?.body).toEqual({ office_code: "HEALTH" }),
    );
    expect(api.calls.some((c) => c.path.startsWith("/custody/recipients?department="))).toBe(false);
  });

  it("Claim on a result shows the API's message when the ownership answers 404", async () => {
    const own = "/cases/ASLMS-GOA-CASE-2026-000003";
    const api = browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [item(3, { visible: false, claimable: true })], total: 1 },
      [`GET ${own}/ownership`]: json(404, { detail: "no such case" }),
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const row = (await screen.findByText("WP(C)/3/2026")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Claim" }));
    const dialog = screen.getByRole("dialog", { name: "Claim this case" });
    expect(await within(dialog).findByText("no such case")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("a single visible match by CNR opens the case page", async () => {
    browserApi({
      "GET /me": me(READER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [item(4, { match: "cnr" })], total: 1 },
    });
    renderWithClient(<Search params={{ q: "ASHC010004002026" }} />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/cases/ASLMS-GOA-CASE-2026-000004"));
  });

  it("the text tab shows only with documents.view", async () => {
    browserApi({ "GET /me": me(["cases.view_scope"]), "GET /reference/case-types": TYPES, "GET /cases": { items: [], total: 0 } });
    const { unmount } = renderWithClient(<Search params={{}} />);
    await screen.findByRole("heading", { name: /Your cases/ });
    expect(screen.queryByRole("link", { name: "Order and document text" })).toBeNull();
    unmount();
    const api = browserApi({
      "GET /me": me(READER),
      "GET /documents/search": { items: [], total: 0 },
    });
    renderWithClient(<Search params={{ tab: "text", q: "eviction" }} />);
    expect(await screen.findByRole("link", { name: "Order and document text" })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/documents/search?q=eviction"))).toBe(true));
  });

  it("the text tab says scanned documents, images and old Word files are not searched (document-ocr)", async () => {
    browserApi({ "GET /me": me(READER), "GET /documents/search": { items: [], total: 0 } });
    renderWithClient(<Search params={{ tab: "text" }} />);
    expect(
      await screen.findByText("Scanned documents, images and old Word files are not searched by their content."),
    ).toBeInTheDocument();
  });
});

describe("court search", () => {
  it("the court panel shows only with cases.search_court", async () => {
    browserApi({ "GET /me": me(READER), "GET /reference/case-types": TYPES, "GET /cases/search": { items: [], total: 0 } });
    renderWithClient(<Search params={{ q: "NOBODY HERE" }} />);
    await screen.findByText("No case matches in the portal's database.");
    expect(screen.queryByRole("region", { name: "Search the court" })).toBeNull();
  });

  it.each([
    [503, { code: "napix_off", message: "off" }, "The court gateway is switched off on this server."],
    [503, { code: "napix_budget", message: "low", retry_after: 600 }, "Try again in 10 minutes."],
    [429, { code: "search_limit", message: "limit", retry_after: 120 }, "Try again in 2 minutes."],
    [502, { code: "napix_unavailable", message: "x" }, "The court gateway did not answer properly. Try again later."],
    [504, { code: "napix_timeout", message: "x" }, "The court gateway took too long to answer. Try again later."],
    [404, { code: "not_found_at_court", message: "x" }, "The court does not know that case number."],
    [400, { code: "bad_input", message: "the CNR is not valid" }, "the CNR is not valid"],
  ])("a %s %o shows its message", async (status, detail, text) => {
    browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [], total: 0 },
      "POST /cases/search-court": json(status, { detail }),
    });
    renderWithClient(<Search params={{ q: "ASHC010099992026" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    expect(within(panel).getByLabelText("CNR (16 characters)")).toHaveValue("ASHC010099992026");
    await userEvent.click(within(panel).getByRole("button", { name: "Search the court" }));
    expect(await within(panel).findByText(new RegExp(text.replace(/[.()]/g, "\\$&")))).toBeInTheDocument();
  });

  it("the button is disabled while a search runs and the answer lists the cases and unmatched rows", async () => {
    let release: (r: Response) => void = () => undefined;
    const pending = new Promise<Response>((r) => {
      release = r;
    });
    const api = browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [], total: 0 },
      "POST /cases/search-court": () => pending,
      "POST /cases/ASLMS-GOA-CASE-2026-000005/fetch-court": item(5, { match: "cnr" }),
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    expect(within(panel).getByLabelText("Party name")).toHaveValue("RAM KUMAR");
    await userEvent.type(within(panel).getByLabelText("Year"), "2025");
    const button = within(panel).getByRole("button", { name: "Search the court" });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(api.calls.filter((c) => c.path === "/cases/search-court")).toHaveLength(1);
    expect(api.calls.find((c) => c.path === "/cases/search-court")!.body).toEqual({
      kind: "party",
      name: "RAM KUMAR",
      reg_year: 2025,
      pend_disp: "P",
    });
    release(
      json(200, {
        source: "party",
        calls: 2,
        created: 1,
        items: [item(5, { dossier_status: "not_fetched", match: "party" })],
        unmatched: [{ type_name: "WP(C)", reg_no: "77", reg_year: "2025", pet_name: "X", res_name: "Y" }],
      }),
    );
    expect(await within(panel).findByText("1 case(s) found; 1 new to the portal.")).toBeInTheDocument();
    expect(within(panel).queryByText(/court call/)).toBeNull(); // no call counts to users (14 Oct owner rule)
    expect(within(panel).getByText(/WP\(C\) 77\/2025 — X vs Y/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Fetch details" }));
    await waitFor(() => expect(within(panel).queryByRole("button", { name: "Fetch details" })).toBeNull());
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/cases/ASLMS-GOA-CASE-2026-000005/fetch-court")).toBe(true);
  });
});

describe("court search by advocate name and filing number (search-court-advocate-filing)", () => {
  function court(extra: Record<string, unknown> = {}) {
    return browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [], total: 0 },
      "POST /cases/search-court": {
        source: "court",
        calls: 1,
        created: 1,
        items: [item(5, { dossier_status: "not_fetched", match: "advocate" })],
        unmatched: [],
      },
      "POST /cases/ASLMS-GOA-CASE-2026-000005/fetch-court": item(5, { match: "advocate" }),
      ...extra,
    });
  }

  it("the Search by choice offers the five kinds", async () => {
    court();
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    const select = within(panel).getByLabelText("Search by");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "CNR",
      "Case type, number and year",
      "Filing number",
      "Party name",
      "Advocate name",
    ]);
  });

  it("Advocate name sends kind advocate with name, year and pending / disposed; Fetch details calls fetch-court", async () => {
    const api = court();
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    await userEvent.selectOptions(within(panel).getByLabelText("Search by"), "advocate");
    expect(within(panel).getByText(/type the full name for precise results/)).toBeInTheDocument();
    await userEvent.type(within(panel).getByLabelText("Advocate name"), "P J SAIKIA");
    await userEvent.type(within(panel).getByLabelText("Year"), "2025");
    await userEvent.selectOptions(within(panel).getByLabelText("Cases"), "both");
    await userEvent.click(within(panel).getByRole("button", { name: "Search the court" }));
    expect(await within(panel).findByText("1 case(s) found; 1 new to the portal.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/cases/search-court")!.body).toEqual({
      kind: "advocate",
      name: "P J SAIKIA",
      reg_year: 2025,
      pend_disp: "both",
    });
    await userEvent.click(within(panel).getByRole("button", { name: "Fetch details" }));
    await waitFor(() => expect(within(panel).queryByRole("button", { name: "Fetch details" })).toBeNull());
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/cases/ASLMS-GOA-CASE-2026-000005/fetch-court")).toBe(true);
  });

  it("Filing number sends kind filing with the filing case type, number and year", async () => {
    const api = court({
      "POST /cases/search-court": { source: "court", calls: 2, created: 1, items: [item(6, { match: "filing" })], unmatched: [] },
    });
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    await userEvent.selectOptions(within(panel).getByLabelText("Search by"), "filing");
    await userEvent.selectOptions(await within(panel).findByLabelText("Filing case type"), "WP(C)");
    await userEvent.type(within(panel).getByLabelText("Filing number"), "6780");
    await userEvent.type(within(panel).getByLabelText("Filing year"), "2025");
    await userEvent.click(within(panel).getByRole("button", { name: "Search the court" }));
    expect(await within(panel).findByText("1 case(s) found; 1 new to the portal.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/cases/search-court")!.body).toEqual({
      kind: "filing",
      case_type: "WP(C)",
      fil_no: 6780,
      fil_year: 2025,
    });
  });

  it("a local search with the advocate field opens the court search on Advocate name with the same words", async () => {
    const api = court();
    renderWithClient(<Search params={{ q: "P J SAIKIA", field: "advocate" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    expect(within(panel).getByLabelText("Search by")).toHaveValue("advocate");
    expect(within(panel).getByLabelText("Advocate name")).toHaveValue("P J SAIKIA");
    expect(api.calls.find((c) => c.path.startsWith("/cases/search?"))!.path).toContain("field=advocate");
  });
});

describe("the filter bar on Search (portal-filters)", () => {
  const SHARED = { case_status: "disposed", owner: "FIN", court_no: "3", bench: "SAIKIA", next_from: "2026-10-01", next_to: "2026-10-31" };
  const parts = ["case_status=disposed", "owner=FIN", "court_no=3", "bench=SAIKIA", "next_from=2026-10-01", "next_to=2026-10-31"];

  it("without words: /cases with case_status, owner, court, bench and the next range; no case_state", async () => {
    const api = browserApi({ "GET /me": me(READER), "GET /reference/case-types": TYPES, "GET /cases": { items: [], total: 0 } });
    renderWithClient(<Search params={SHARED} />);
    await screen.findByRole("heading", { name: /Your cases/ });
    const call = api.calls.find((c) => c.path.startsWith("/cases?"))!;
    for (const part of parts) expect(call.path).toContain(part);
    expect(call.path).not.toContain("case_state");
    expect(screen.queryByRole("combobox", { name: "Cases" })).toBeNull(); // Status replaces Active / Disposed / All
  });

  it("with words: /cases/search with the same filters", async () => {
    const api = browserApi({ "GET /me": me(READER), "GET /reference/case-types": TYPES, "GET /cases/search": { items: [], total: 0 } });
    renderWithClient(<Search params={{ ...SHARED, q: "ram kumar" }} />);
    await screen.findByRole("heading", { name: /Results/ });
    const call = api.calls.find((c) => c.path.startsWith("/cases/search"))!;
    for (const part of [...parts, "q=ram+kumar"]) expect(call.path).toContain(part);
  });

  it("an old status=disposed&office=FIN link is sent as case_status and owner", async () => {
    const api = browserApi({ "GET /me": me(READER), "GET /reference/case-types": TYPES, "GET /cases": { items: [], total: 0 } });
    renderWithClient(<Search params={{ status: "disposed", office: "FIN" }} />);
    await screen.findByRole("heading", { name: /Your cases/ });
    const call = api.calls.find((c) => c.path.startsWith("/cases?"))!;
    expect(call.path).toContain("case_status=disposed");
    expect(call.path).toContain("owner=FIN");
    expect(call.path).not.toMatch(/[?&](status|office)=/);
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/search?case_status=disposed&owner=FIN");
  });

  it("the text tab sends group, doc_type, date_from and date_to", async () => {
    const api = browserApi({
      "GET /me": me(READER),
      "GET /documents/types": {
        items: [{ code: "order", label: "Order", doc_group: "court_record", group_choosable: false }],
        upload: { max_bytes: 1, allowed_types: [] },
      },
      "GET /documents/search": { items: [], total: 0 },
    });
    renderWithClient(
      <Search
        params={{ tab: "text", q: "eviction", group: "court_record", doc_type: "order", date_from: "2026-01-01", date_to: "2026-06-30" }}
      />,
    );
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith("/documents/search"))).toBe(true));
    const call = api.calls.find((c) => c.path.startsWith("/documents/search"))!;
    for (const part of ["q=eviction", "group=court_record", "doc_type=order", "date_from=2026-01-01", "date_to=2026-06-30"]) {
      expect(call.path).toContain(part);
    }
    expect(screen.getByText("Document group: Court orders")).toBeInTheDocument();
  });

  it("the text tab refuses a reversed document date range", async () => {
    const api = browserApi({ "GET /me": me(READER), "GET /documents/types": { items: [], upload: {} } });
    renderWithClient(<Search params={{ tab: "text" }} />);
    await userEvent.type(await screen.findByLabelText("Words in orders and documents"), "eviction");
    await userEvent.type(screen.getByLabelText("Document date from"), "2026-06-30");
    await userEvent.type(screen.getByLabelText("Document date to"), "2026-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByText("The start date is after the end date.")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
    expect(api.calls.some((c) => c.path.startsWith("/documents/search"))).toBe(false);
  });
});

describe("court search caps (safety-fixes, decision 14)", () => {
  async function runAdvocate(answer: Record<string, unknown>) {
    browserApi({
      "GET /me": me(SEARCHER),
      "GET /reference/case-types": TYPES,
      "GET /cases/search": { items: [], total: 0 },
      "POST /cases/search-court": answer,
    });
    renderWithClient(<Search params={{ q: "SAIKIA" }} />);
    const panel = await screen.findByRole("region", { name: "Search the court" });
    await userEvent.selectOptions(within(panel).getByLabelText("Search by"), "advocate");
    await userEvent.type(within(panel).getByLabelText("Advocate name"), "SAIKIA");
    await userEvent.type(within(panel).getByLabelText("Year"), "2025");
    await userEvent.click(within(panel).getByRole("button", { name: "Search the court" }));
    return panel;
  }

  it("court search shows the queued and not-stored notices", async () => {
    const queued = await runAdvocate({
      source: "court",
      calls: 1,
      created: 25,
      items: [item(5, { match: "advocate" })],
      unmatched: [],
      court_cases: 30,
      queued: 5,
      not_stored: 0,
    });
    expect(await within(queued).findByText("5 more cases are being added; search the portal again in a minute.")).toBeInTheDocument();
    expect(within(queued).queryByText(/Type more of the name/)).toBeNull();
  });

  it("an over-cap advocate search asks for more of the name", async () => {
    const capped = await runAdvocate({
      source: "court",
      calls: 1,
      created: 25,
      items: [item(5, { match: "advocate" })],
      unmatched: [],
      court_cases: 325,
      queued: 0,
      not_stored: 300,
    });
    expect(
      await within(capped).findByText(
        "The court found 325 cases for this name; only the first 25 new ones were added. Type more of the name (initials and surname) to narrow it.",
      ),
    ).toBeInTheDocument();
    expect(within(capped).queryByText(/more cases are being added/)).toBeNull();
  });
});

describe("the Work list template on Search (portal-ui-redesign, decision 26)", () => {
  const routes = (items: CaseSearchItem[]) => ({
    "GET /me": me(SEARCHER),
    "GET /reference/case-types": TYPES,
    "GET /cases/search": { items, total: items.length },
    "GET /cases": { items, total: items.length },
  });

  it("a row opens the side panel with the facts and Open case page; Close closes it", async () => {
    browserApi(routes([item(1, { owner_office_code: "EDU" })]));
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/1/2026" }));
    const panel = await screen.findByRole("dialog", { name: "WP(C)/1/2026" });
    expect(within(panel).getByText("Owned by EDU")).toBeInTheDocument();
    expect(within(panel).getByText("ASHC010001002026")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open case page" })).toHaveAttribute("href", "/cases/ASLMS-GOA-CASE-2026-000001");
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a case the caller cannot open has no Open case page in the panel, and Claim when claimable", async () => {
    browserApi(routes([item(3, { visible: false, in_pool: true, claimable: true })]));
    renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    await userEvent.click(await screen.findByRole("row", { name: "Details of WP(C)/3/2026" }));
    const panel = await screen.findByRole("dialog", { name: "WP(C)/3/2026" });
    expect(within(panel).queryByRole("link")).toBeNull();
    await userEvent.click(within(panel).getByRole("button", { name: "Claim" }));
    expect(await screen.findByRole("dialog", { name: "Claim this case" })).toBeInTheDocument();
  });

  it("cards on phones (every cell labelled) and at most one primary on the page", async () => {
    browserApi(routes([item(1), item(2, { claimable: true, visible: false })]));
    const { container } = renderWithClient(<Search params={{ q: "RAM KUMAR" }} />);
    const table = await screen.findByRole("table", { name: "Results" });
    for (const row of within(table).getAllByRole("row").slice(1)) {
      const cells = within(row).getAllByRole("cell");
      expect(cells[0]).not.toHaveAttribute("data-label"); // the primary cell tops the card
      expect(cells[1]).toHaveAttribute("data-label", "Status");
    }
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });
});

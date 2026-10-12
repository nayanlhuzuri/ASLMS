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
    expect(await within(panel).findByText("1 case(s) found with 2 court call(s); 1 new to the portal.")).toBeInTheDocument();
    expect(within(panel).getByText(/WP\(C\) 77\/2025 — X vs Y/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Fetch details" }));
    await waitFor(() => expect(within(panel).queryByRole("button", { name: "Fetch details" })).toBeNull());
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/cases/ASLMS-GOA-CASE-2026-000005/fetch-court")).toBe(true);
  });
});

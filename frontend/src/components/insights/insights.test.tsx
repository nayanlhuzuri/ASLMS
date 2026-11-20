import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { nav, resetNav } from "@/test/nav";
import { caseItem, casesPage, FIELDS, overview, SCOPES_ONE, SCOPES_STATE } from "@/test/insightsFixtures";
import { resetRecharts } from "@/test/rechartsMock";
import { browserApi, json, renderWithClient, type BrowserCall } from "@/test/render";

import { CaseList, stateWords } from "./CaseList";
import { InsightsPage } from "./InsightsPage";

vi.mock("recharts", async () => (await import("@/test/rechartsMock")).rechartsModule);

const overviewCalls = (calls: BrowserCall[]) => calls.filter((c) => c.method === "GET" && /^\/insights(\?|$)/.test(c.path));
const queryOf = (call: BrowserCall) => new URL(call.path, "http://x").searchParams;

function routes(extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /insights/scopes": SCOPES_STATE,
    "GET /insights": overview(),
    "GET /insights/cases": casesPage([caseItem(1)]),
    "GET /insights/fields": FIELDS,
    "GET /reference/offices": { items: [] },
    ...extra,
  });
}

beforeEach(() => {
  resetNav("/insights");
  resetRecharts();
});

describe("the Insights page (design state-insights, decisions 31 and 32)", () => {
  it("reads the filters from the URL and writes every change back with router.replace", async () => {
    const api = routes();
    const { rerender } = renderWithClient(<InsightsPage params={{ kind: "contempt", junk: "x" }} />);
    await screen.findByRole("button", { name: /Over 5 Years/ });
    expect(queryOf(overviewCalls(api.calls)[0]!).get("kind")).toBe("contempt");
    expect(queryOf(overviewCalls(api.calls)[0]!).has("junk")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /Over 5 Years/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?kind=contempt&age=over_5", { scroll: false });
    // Back: the address changes under the page, and the page follows it
    rerender(<InsightsPage params={{}} />);
    await waitFor(() => expect(queryOf(overviewCalls(api.calls).at(-1)!).toString()).toBe(""));
  });

  it("a headline figure sets its filter and a second click removes it", async () => {
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    const contempt = await screen.findByRole("button", { name: /Contempt Cases/ });
    expect(contempt).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(contempt);
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?kind=contempt", { scroll: false });
    expect(screen.getByRole("button", { name: /Contempt Cases/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: /Contempt Cases/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights", { scroll: false });
  });

  it("each headline figure sets its own filter; Cases sets none", async () => {
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: /Hearing in Next 7 Days/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?next=within_7", { scroll: false });
    await userEvent.click(screen.getByRole("button", { name: /Not Claimed by Any Department/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?next=within_7&action=not_claimed", { scroll: false });
    expect(screen.getByRole("button", { name: /^Cases/ })).toBeDisabled();
  });

  it("a chip's removal and Clear All", async () => {
    routes({
      "GET /insights": overview({
        chips: [
          { param: "kind", value: "contempt", label: "Kind: Contempt" },
          { param: "dept", value: "EDU", label: "School Education · Likely" },
        ],
      }),
    });
    renderWithClient(<InsightsPage params={{ status: "all", kind: "contempt", dept: "EDU", band: "likely" }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove filter School Education · Likely" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?status=all&kind=contempt", { scroll: false });
    await userEvent.click(screen.getByRole("button", { name: "Clear All" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?status=all", { scroll: false });
  });

  it("shows the view switch only when there is more than one choice", async () => {
    routes({ "GET /insights/scopes": SCOPES_ONE });
    const first = renderWithClient(<InsightsPage params={{}} />);
    await screen.findByRole("button", { name: /Contempt Cases/ });
    expect(screen.queryByRole("combobox", { name: "View" })).toBeNull();
    first.unmount();
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    const view = await screen.findByRole("combobox", { name: "View" });
    expect(within(view).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Whole State",
      "School Education",
      "Health and Family Welfare",
    ]);
    await userEvent.selectOptions(view, "department:HEALTH");
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?scope=department&department=HEALTH", { scroll: false });
  });

  it("asks once after the changes settle and cancels the earlier request", async () => {
    let first: AbortSignal | undefined;
    const api = browserApi({
      "GET /insights/scopes": SCOPES_STATE,
      "GET /insights/cases": casesPage([]),
      "GET /reference/offices": { items: [] },
    });
    // the first overview never answers; later ones do
    api.fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      api.calls.push({ method: (init?.method ?? "GET").toUpperCase(), url, path: url.replace("/api/backend", ""), body: undefined });
      if (/\/insights\/scopes/.test(url)) return json(200, SCOPES_STATE);
      if (/\/insights\/cases/.test(url)) return json(200, casesPage([]));
      if (/\/insights(\?|$)/.test(url)) {
        if (!first) {
          first = init?.signal ?? undefined;
          return new Promise<Response>(() => undefined);
        }
        return json(200, overview());
      }
      return json(404, {});
    });
    renderWithClient(<InsightsPage params={{}} />);
    await waitFor(() => expect(overviewCalls(api.calls)).toHaveLength(1));
    const group = screen.getByRole("radiogroup", { name: "Cases" });
    await userEvent.click(within(group).getByRole("radio", { name: "Disposed" }));
    await userEvent.click(within(group).getByRole("radio", { name: "All" }));
    await screen.findByRole("button", { name: /Contempt Cases/ });
    const asked = overviewCalls(api.calls);
    expect(asked).toHaveLength(2);
    expect(queryOf(asked[1]!).get("status")).toBe("all");
    expect(first?.aborted).toBe(true);
  });

  it("says so when no case matches", async () => {
    routes({
      "GET /insights": overview({ headline: { ...overview().headline, cases: 0 } }),
      "GET /insights/cases": casesPage([]),
    });
    renderWithClient(<InsightsPage params={{ kind: "contempt" }} />);
    expect((await screen.findAllByText("No case matches this selection.")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Next Hearing" })).toBeNull();
  });

  it("a slow selection says to narrow it, with Try Again", async () => {
    const api = routes({
      "GET /insights": json(503, { detail: { code: "insights_timeout", message: "the statement timed out" } }),
    });
    renderWithClient(<InsightsPage params={{}} />);
    expect(await screen.findByText("This selection took too long. Narrow it and try again.")).toBeInTheDocument();
    const before = overviewCalls(api.calls).length;
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Try Again" }));
    });
    expect(overviewCalls(api.calls).length).toBe(before + 1);
  });

  it("the toggles and the status switch keep their defaults out of the URL", async () => {
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    await screen.findByRole("button", { name: /Contempt Cases/ });
    await userEvent.click(screen.getByRole("checkbox", { name: "State Cases Only" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?state_only=false", { scroll: false });
    await userEvent.click(screen.getByRole("checkbox", { name: "Include Interlocutory Applications" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/insights?state_only=false&include_ia=true", { scroll: false });
  });

  it("the quick dates fill Date Of, From and To", async () => {
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    await userEvent.click(screen.getByRole("button", { name: "Next 7 Days (Hearing)" }));
    const last = nav.replace.mock.calls.at(-1)![0] as string;
    expect(last).toMatch(/^\/insights\?date_of=next_hearing&from=\d{4}-\d\d-\d\d&to=\d{4}-\d\d-\d\d$/);
  });

  it("prints the coverage and the applications counted inside their main case", async () => {
    routes();
    renderWithClient(<InsightsPage params={{}} />);
    expect(await screen.findByText(/^14 pending interlocutory applications are counted inside their main case \(2 whose/)).toBeInTheDocument();
  });
});

describe("the case list (decision 26)", () => {
  it("shows who has each case, the state-case words and the applications, 20 a page", async () => {
    const api = routes({
      "GET /insights/cases": casesPage(
        [
          caseItem(1, {
            who: { kind: "recommended", text: "Not Claimed · Recommended to School Education and 2 more", recommended_to: "EDU", more: 2 },
            applications_pending: 3,
          }),
          caseItem(2, { phrases_unmapped: ["FINANCE"], state_case: false, state_basis: [] }),
        ],
        45,
      ),
    });
    const onChange = vi.fn();
    renderWithClient(<CaseList params={{ kind: "wp" }} settledFilters="?kind=wp" onChange={onChange} />);
    const table = await screen.findByRole("table", { name: "Cases in This Selection" });
    expect(within(table).getByRole("link", { name: "WP(C)/1/2026" })).toHaveAttribute("href", "/cases/ASLMS-GHC-CASE-2026-000001");
    expect(within(table).getByText("State Case: Yes (Parties, Counsel Code)")).toBeInTheDocument();
    expect(within(table).getByText("Applications Pending: 3")).toBeInTheDocument();
    expect(within(table).getByText(/Recommended to/)).toHaveTextContent("and 2 more");
    expect(within(table).getByText("As read: FINANCE")).toBeInTheDocument();
    expect(screen.getByText("45 cases")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onChange).toHaveBeenLastCalledWith({ kind: "wp", page: "2" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Sort By" }), "registered");
    expect(onChange).toHaveBeenLastCalledWith({ kind: "wp", sort: "registered" });
    expect(api.calls.find((c) => c.path.startsWith("/insights/cases"))!.path).toBe("/insights/cases?kind=wp");
  });

  it("names the bases in words", () => {
    expect(stateWords({ state_case: true, state_basis: ["officer", "title", "claimed"] })).toBe("Yes (Officer Named, Cause Title, Claimed)");
    expect(stateWords({ state_case: false, state_basis: [] })).toBe("No");
  });
});

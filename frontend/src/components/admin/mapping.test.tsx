import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { CounselCode, Keyword, Me, NamePattern, OfficeChoice, Permission, ScoringSettings, UnmappedCode, Watch } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, primaryActions, renderWithClient, type BrowserCall } from "@/test/render";

import { CounselCodes } from "./mapping/CounselCodes";
import { KeywordsAndPatterns } from "./mapping/Keywords";
import { Scoring, sliderValue } from "./mapping/Scoring";
import { Watchlist } from "./mapping/Watchlist";

const RULES: Permission[] = ["admin.counsel_codes", "admin.keywords", "admin.watchlist"];

function deptAdmin(functions: Permission[] = RULES): Me {
  return makeMe(functions, "dept_admin");
}

function superAdmin(): Me {
  return makeMe([...RULES, "users.view", "admin.scoring"], "super_admin", {
    memberships: [
      {
        id: "m-0",
        office: { code: "GOA", name: "Government of Assam", kind: "state" },
        department_code: null,
        designation: null,
        role: "super_admin",
        is_primary: true,
        is_active: true,
      },
    ],
  });
}

function choice(code: string, name: string, depth: number, parent: string | null, kind = "department"): OfficeChoice {
  const ancestors = depth === 0 ? [] : depth === 1 ? ["Government of Assam"] : ["Government of Assam", "Education"];
  return { code, name, kind, tier: kind === "state" ? "state" : "department", depth, parent_code: parent, ancestors, is_active: true };
}

const ROOT = choice("GOA", "Government of Assam", 0, null, "state");
const EDU = choice("EDU", "Education", 1, "GOA");
const DSE = choice("EDU-DSE", "Secondary Education", 2, "EDU", "directorate");
const HEALTH = choice("HEALTH", "Health", 1, "GOA");

/** The choices answer for whichever purpose was asked. */
function choices(items: OfficeChoice[]) {
  return (call: BrowserCall) => ({ purpose: new URL(call.path, "http://x").searchParams.get("purpose"), items });
}

function code(extra: Partial<CounselCode> = {}): CounselCode {
  return {
    id: "cc-1",
    code: "SC, EDU",
    office: { code: "EDU", name: "Education" },
    weight_override: null,
    effective_weight: 0.9,
    is_generic_state: false,
    notes: null,
    is_active: true,
    updated_at: "2026-10-10T05:00:00Z",
    ...extra,
  };
}

function keyword(extra: Partial<Keyword> = {}): Keyword {
  return {
    id: "kw-1",
    keyword: "DIRECTOR OF SECONDARY EDUCATION",
    office: { code: "EDU", name: "Education" },
    weight_override: null,
    effective_weight: 0.4,
    is_active: true,
    updated_at: "2026-10-10T05:00:00Z",
    discover: true,
    discoverable: true,
    discovery: null,
    ...extra,
  };
}

function pattern(extra: Partial<NamePattern> = {}): NamePattern {
  return {
    id: "np-1",
    pattern: "STATE OF ASSAM",
    kind: "prefix",
    office: { code: "HEALTH", name: "Health" },
    weight_override: null,
    effective_weight: 0.6,
    is_active: true,
    updated_at: "2026-10-10T05:00:00Z",
    discover: false,
    discoverable: true,
    discovery: null,
    ...extra,
  };
}

function watch(extra: Partial<Watch> = {}): Watch {
  return {
    id: "w-1",
    cnr: "ASHC010012342025",
    case_ref: "ASLMS/GOA/CASE/2025/000001",
    office: { code: "EDU", name: "Education" },
    reason: "asked by the department",
    weight_override: null,
    effective_weight: 0.95,
    is_active: true,
    updated_at: "2026-10-10T05:00:00Z",
    ...extra,
  };
}

function settings(version: number, extra: Partial<ScoringSettings> = {}): ScoringSettings {
  return {
    version,
    weights: { counsel_code: 0.9, counsel_code_partial: 0.6, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.4 },
    thresholds: { strong: 0.85, possible: 0.5 },
    reason: version === 0 ? null : "initial",
    valid_from: version === 0 ? null : "2026-10-01T05:00:00Z",
    valid_to: null,
    updated_by: version === 0 ? null : { id: "u-0", full_name: "Super Admin" },
    engine_version: "m1",
    ...extra,
  };
}

const calls = (api: { calls: BrowserCall[] }, method: string, path: string) =>
  api.calls.filter((c) => c.method === method && c.path.split("?")[0] === path);

async function chooseOffice(box: HTMLElement, name: string) {
  await userEvent.click(box);
  await userEvent.click(within(await screen.findByRole("listbox")).getByText(name));
}

/** Opens a row's menu (the kebab) and chooses an item. */
async function rowAction(what: string, item: string) {
  await userEvent.click(screen.getByRole("button", { name: `More actions for ${what}` }));
  await userEvent.click(screen.getByRole("menuitem", { name: item }));
}

beforeEach(() => {
  resetNav("/admin/mapping/codes");
});

describe("counsel codes (design portal-ui-polish-2, decisions 39-42)", () => {
  it("the add row has no Notes or Weight, even with admin.scoring, and the body never carries notes or weight", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices/choices": choices([ROOT, EDU, DSE, HEALTH]),
      "GET /admin/counsel-codes": { items: [code({ weight_override: 0.7, notes: "kept" })], total: 1 },
      "GET /admin/counsel-codes/unmapped": [],
      "POST /admin/counsel-codes": json(201, { ...code({ id: "cc-2", code: "SC, DSE" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("SC, EDU")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Add Code" });
    expect(within(form).queryByLabelText(/Notes/)).toBeNull();
    expect(within(form).queryByLabelText(/Weight/)).toBeNull();
    // the list's Notes and Weight columns are gone
    const table = screen.getByRole("table", { name: "Counsel Codes" });
    expect(within(table).queryByText("Notes")).toBeNull();
    expect(within(table).queryByText(/Weight/)).toBeNull();
    expect(within(table).queryByText("kept")).toBeNull();
    await userEvent.type(within(form).getByLabelText("Code"), "SC, DSE");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Secondary Education");
    await userEvent.click(within(form).getByRole("button", { name: "Add Code" }));
    expect(await screen.findByText("Takes effect at the next rescore, within 15 minutes.")).toBeInTheDocument();
    expect(calls(api, "POST", "/admin/counsel-codes")[0]!.body).toEqual({ code: "SC, DSE", office_code: "EDU-DSE", is_generic_state: false });
    // the add row's submit is secondary: the mapping page keeps no primary of its own
    expect(within(form).getByRole("button", { name: "Add Code" })).toHaveAttribute("data-variant", "secondary");
    expect(calls(api, "GET", "/admin/offices/choices")[0]!.path).toContain("purpose=counsel_codes");
  });

  it("the root office makes the code generic; any other office does not", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices/choices": choices([ROOT, EDU, HEALTH]),
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": [],
      "POST /admin/counsel-codes": json(201, { ...code({ code: "PP, ASSAM" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    const form = await screen.findByRole("form", { name: "Add Code" });
    await userEvent.type(within(form).getByLabelText("Code"), "PP, ASSAM");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Government of Assam");
    expect(within(form).getByText(/A code mapped to the State is generic/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Add Code" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/counsel-codes")).toHaveLength(1));
    expect(calls(api, "POST", "/admin/counsel-codes")[0]!.body).toMatchObject({ office_code: "GOA", is_generic_state: true });

    await userEvent.type(within(form).getByLabelText("Code"), "SC, HEALTH");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Health");
    expect(within(form).queryByText(/A code mapped to the State is generic/)).toBeNull();
    await userEvent.click(within(form).getByRole("button", { name: "Add Code" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/counsel-codes")).toHaveLength(2));
    expect(calls(api, "POST", "/admin/counsel-codes")[1]!.body).toMatchObject({ office_code: "HEALTH", is_generic_state: false });
  });

  it("the toolbar sends q and include_inactive on one line", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
      "GET /admin/counsel-codes/unmapped": [],
    });
    renderWithClient(<CounselCodes />);
    await screen.findByText("SC, EDU");
    const bar = screen.getByRole("search", { name: "Search Codes" });
    await userEvent.type(within(bar).getByRole("searchbox", { name: "Search Codes" }), "edu");
    await userEvent.click(within(bar).getByRole("switch", { name: "Include Deactivated" }));
    await waitFor(() =>
      expect(calls(api, "GET", "/admin/counsel-codes").some((c) => c.path.includes("q=edu") && c.path.includes("include_inactive=true"))).toBe(true),
    );
  });

  it("a row's menu changes the office with the picker (PATCH office_code only) and deactivates after asking", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
      "GET /admin/counsel-codes/unmapped": [],
      "PATCH /admin/counsel-codes/cc-1": { ...code({ office: { code: "EDU-DSE", name: "Secondary Education" } }), applies_within_minutes: 15 },
      "POST /admin/counsel-codes/cc-1/deactivate": { ...code({ is_active: false }), applies_within_minutes: 15 },
    });
    renderWithClient(<CounselCodes />);
    await screen.findByText("SC, EDU");
    await rowAction("SC, EDU", "Change Office");
    const dialog = await screen.findByRole("dialog", { name: "Change Office" });
    await chooseOffice(within(dialog).getByRole("combobox", { name: "Office" }), "Secondary Education");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(1));
    expect(calls(api, "PATCH", "/admin/counsel-codes/cc-1")[0]!.body).toEqual({ office_code: "EDU-DSE" });

    await rowAction("SC, EDU", "Deactivate");
    const confirm = await screen.findByRole("dialog", { name: "Deactivate This Rule" });
    expect(calls(api, "POST", "/admin/counsel-codes/cc-1/deactivate")).toHaveLength(0);
    await userEvent.click(within(confirm).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/counsel-codes/cc-1/deactivate")).toHaveLength(1));
  });

  it("generic rows have no menu when the root office is not among the choices", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": {
        items: [code(), code({ id: "cc-9", code: "PP, ASSAM", is_generic_state: true, office: { code: "GOA", name: "Government of Assam" } })],
        total: 2,
      },
      "GET /admin/counsel-codes/unmapped": [],
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("PP, ASSAM")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "More actions for SC, EDU" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "More actions for PP, ASSAM" })).toBeNull();
  });

  it("Recommended From Cause Lists is always shown; Map posts the code with the chosen office and the code leaves", async () => {
    const unmapped: UnmappedCode[] = [
      { code: "SC, PWD", entries: 1240, last_listed: "2026-10-09", example_case_ref: "ASLMS/GOA/CASE/2026/000042", partial_matches: [] },
      { code: "SC, AGRI", entries: 12, last_listed: "2026-10-01", example_case_ref: null, partial_matches: [] },
    ];
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": unmapped,
      "POST /admin/counsel-codes": json(201, { ...code({ id: "cc-5", code: "SC, PWD" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    const panel = await screen.findByRole("complementary", { name: "Recommended From Cause Lists" });
    expect(await within(panel).findByText("SC, PWD")).toBeInTheDocument();
    expect(within(panel).getByText("2 to review")).toBeInTheDocument();
    expect(within(panel).getByText("Nothing is mapped automatically.")).toBeInTheDocument();
    expect(calls(api, "GET", "/admin/counsel-codes/unmapped")[0]!.url).toContain("limit=100");
    expect(within(panel).getByRole("link", { name: "ASLMS/GOA/CASE/2026/000042" })).toHaveAttribute("href", "/search?q=ASLMS%2FGOA%2FCASE%2F2026%2F000042");
    expect(within(panel).getByText(/1,240 entries · last seen/)).toBeInTheDocument();
    const map = within(panel).getByRole("form", { name: "Map SC, PWD" });
    expect(within(map).getByRole("button", { name: "Map SC, PWD" })).toBeDisabled();
    await chooseOffice(within(map).getByRole("combobox", { name: "Office for SC, PWD" }), "Education");
    await userEvent.click(within(map).getByRole("button", { name: "Map SC, PWD" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/counsel-codes")).toHaveLength(1));
    expect(calls(api, "POST", "/admin/counsel-codes")[0]!.body).toEqual({ code: "SC, PWD", office_code: "EDU", is_generic_state: false });
    await waitFor(() => expect(within(panel).queryByText("SC, PWD")).toBeNull());
    expect(within(panel).getByText("SC, AGRI")).toBeInTheDocument();
  });

  it("a partly matching code says so, and with one match in scope its picker starts on that office", async () => {
    const unmapped: UnmappedCode[] = [
      {
        code: "SC, EDU, DSE",
        entries: 40,
        last_listed: "2026-10-23",
        example_case_ref: null,
        partial_matches: [{ code: "SC, EDU", office_code: "EDU", relation: "contained" }],
      },
      {
        code: "EDU",
        entries: 3,
        last_listed: "2026-10-20",
        example_case_ref: null,
        partial_matches: [
          { code: "SC, EDU", office_code: "EDU", relation: "contains" },
          { code: "SC, EDU, DSE", office_code: "EDU-DSE", relation: "contains" },
        ],
      },
    ];
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": unmapped,
      "POST /admin/counsel-codes": json(201, { ...code({ id: "cc-6", code: "SC, EDU, DSE" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    const panel = await screen.findByRole("complementary", { name: "Recommended From Cause Lists" });
    expect(await within(panel).findByText("Partly matches SC, EDU (EDU)")).toBeInTheDocument();
    expect(within(panel).getByText("Partly matches SC, EDU (EDU); SC, EDU, DSE (EDU-DSE)")).toBeInTheDocument();
    // one match: the picker starts on EDU and nothing is sent until Map is pressed
    const single = within(panel).getByRole("form", { name: "Map SC, EDU, DSE" });
    expect(within(single).getByRole("button", { name: "Map SC, EDU, DSE" })).toBeEnabled();
    expect(calls(api, "POST", "/admin/counsel-codes")).toHaveLength(0);
    // two matches: no pre-fill
    expect(within(within(panel).getByRole("form", { name: "Map EDU" })).getByRole("button", { name: "Map EDU" })).toBeDisabled();
    await userEvent.click(within(single).getByRole("button", { name: "Map SC, EDU, DSE" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/counsel-codes")).toHaveLength(1));
    expect(calls(api, "POST", "/admin/counsel-codes")[0]!.body).toEqual({ code: "SC, EDU, DSE", office_code: "EDU", is_generic_state: false });
  });

  it("a failing recommended report shows the API's message with Retry; a 403 on adding shows the server's message", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": json(503, { detail: "the report took too long" }),
      "POST /admin/counsel-codes": json(403, { detail: "the office is outside your offices" }),
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("the report took too long")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Add Code" });
    await userEvent.type(within(form).getByLabelText("Code"), "SC, EDU");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.click(within(form).getByRole("button", { name: "Add Code" }));
    expect((await screen.findAllByText("the office is outside your offices")).length).toBeGreaterThanOrEqual(1);
  });

  it("renders DataTables with a primary cell and no primary button", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU]),
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
      "GET /admin/counsel-codes/unmapped": [],
    });
    const { container } = renderWithClient(<CounselCodes />);
    expectDataTable(await screen.findByRole("table", { name: "Counsel Codes" }));
    expect(primaryActions(container)).toEqual([]);
  });
});

describe("keywords and name patterns", () => {
  function routes(extra: Record<string, unknown> = {}) {
    return browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE, HEALTH]),
      "GET /admin/keywords": { items: [keyword()], total: 1 },
      "GET /admin/name-patterns": { items: [pattern()], total: 1 },
      ...extra,
    });
  }

  it("one list with the kind, the All / Keywords / Name Patterns choice and a search over the words", async () => {
    routes();
    renderWithClient(<KeywordsAndPatterns />);
    const table = await screen.findByRole("table", { name: "Keywords and Name Patterns" });
    expectDataTable(table);
    expect(within(table).getByText("DIRECTOR OF SECONDARY EDUCATION")).toBeInTheDocument();
    expect(within(table).getByText("STATE OF ASSAM")).toBeInTheDocument();
    expect(within(table).getByText("Starts With")).toBeInTheDocument();
    expect(within(table).queryByText(/Weight/)).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "Name Patterns" }));
    expect(screen.queryByText("DIRECTOR OF SECONDARY EDUCATION")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "All" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search Words" }), "secondary");
    expect(screen.queryByText("STATE OF ASSAM")).toBeNull();
    expect(screen.getByText("DIRECTOR OF SECONDARY EDUCATION")).toBeInTheDocument();
  });

  it("the add row routes a keyword to /admin/keywords and the other kinds to /admin/name-patterns, never with a weight", async () => {
    const api = routes({
      "POST /admin/keywords": json(201, { ...keyword({ id: "kw-2", keyword: "COMMISSIONER OF EDUCATION" }), applies_within_minutes: 15 }),
      "POST /admin/name-patterns": json(201, { ...pattern({ id: "np-2" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    const form = await screen.findByRole("form", { name: "Add" });
    expect(within(form).getAllByRole("option").map((o) => o.textContent)).toEqual(["Keyword", "Exact", "Starts With", "Pattern"]);
    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "COMMISSIONER OF EDUCATION");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("Takes effect at the next rescore, within 15 minutes.")).toBeInTheDocument();
    expect(calls(api, "POST", "/admin/keywords")[0]!.body).toEqual({ keyword: "COMMISSIONER OF EDUCATION", office_code: "EDU" });

    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "STATE OF");
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "prefix");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Health");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/name-patterns")).toHaveLength(1));
    expect(calls(api, "POST", "/admin/name-patterns")[0]!.body).toEqual({ pattern: "STATE OF", kind: "prefix", office_code: "HEALTH" });
    expect(calls(api, "GET", "/admin/offices/choices")[0]!.path).toContain("purpose=keywords");
  });

  it("Search the Court follows the text until changed and is off and disabled for a pattern", async () => {
    const api = routes({ "POST /admin/name-patterns": json(201, { ...pattern({ id: "np-3", pattern: "PRITAM" }), applies_within_minutes: 15 }) });
    renderWithClient(<KeywordsAndPatterns />);
    const form = await screen.findByRole("form", { name: "Add" });
    const sw = within(form).getByRole("switch", { name: "Search the Court" });
    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "Dr. Pritam Saikia");
    expect(sw).toHaveAttribute("aria-checked", "true");
    await userEvent.clear(within(form).getByLabelText("Word or Pattern"));
    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "100% pass");
    expect(sw).toHaveAttribute("aria-checked", "false");
    await userEvent.clear(within(form).getByLabelText("Word or Pattern"));
    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "PRITAM");
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "regex");
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).toBeDisabled();
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "prefix");
    expect(sw).toHaveAttribute("aria-checked", "true");
    await userEvent.click(sw); // the person turns it off: sent as false
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/name-patterns")).toHaveLength(1));
    expect(calls(api, "POST", "/admin/name-patterns")[0]!.body).toEqual({ pattern: "PRITAM", kind: "prefix", office_code: "EDU", discover: false });
  });

  it("the row toggle sends PATCH {discover}; Deactivate from the menu asks first; a 409 shows the API's message", async () => {
    const api = routes({
      "GET /admin/keywords": {
        items: [keyword({ discovery: { term_id: "t-1", last_searched_at: "2026-10-13T05:00:00Z", cases_found: 4 } })],
        total: 1,
      },
      "PATCH /admin/keywords/kw-1": { ...keyword({ discover: false }), applies_within_minutes: 15 },
      "POST /admin/keywords/kw-1/deactivate": { ...keyword({ is_active: false }), applies_within_minutes: 15 },
      "POST /admin/keywords": json(409, { detail: "the keyword COMMISSIONER OF EDUCATION already exists for EDU" }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    expect(await screen.findByText(/4 case\(s\) found/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Search the court for DIRECTOR OF SECONDARY EDUCATION"));
    await waitFor(() => expect(calls(api, "PATCH", "/admin/keywords/kw-1")).toHaveLength(1));
    expect(calls(api, "PATCH", "/admin/keywords/kw-1")[0]!.body).toEqual({ discover: false });
    // a row's menu offers no Change Office here: the API takes no office change for a keyword
    await userEvent.click(screen.getByRole("button", { name: "More actions for DIRECTOR OF SECONDARY EDUCATION" }));
    expect(screen.queryByRole("menuitem", { name: "Change Office" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/stops counting at the next rescore, within 15 minutes/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(calls(api, "POST", "/admin/keywords/kw-1/deactivate")).toHaveLength(1));

    const form = screen.getByRole("form", { name: "Add" });
    const before = calls(api, "GET", "/admin/keywords").length;
    await userEvent.type(within(form).getByLabelText("Word or Pattern"), "COMMISSIONER OF EDUCATION");
    await chooseOffice(within(form).getByRole("combobox", { name: "Office" }), "Education");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("the keyword COMMISSIONER OF EDUCATION already exists for EDU")).toBeInTheDocument();
    await waitFor(() => expect(calls(api, "GET", "/admin/keywords").length).toBeGreaterThan(before));
  });
});

describe("watchlist", () => {
  it("refuses a malformed CNR without calling the API", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, DSE]),
      "GET /admin/watchlist": { items: [], total: 0 },
    });
    renderWithClient(<Watchlist />);
    const form = await screen.findByRole("form", { name: "Watchlist" });
    for (const bad of ["ASHC01001234202", "AS1C010012342025", "ASHC01001234202X"]) {
      await userEvent.clear(within(form).getByLabelText("CNR"));
      await userEvent.type(within(form).getByLabelText("CNR"), bad);
      await userEvent.click(within(form).getByRole("button", { name: "Add" }));
      expect(await within(form).findByText("A CNR is four letters followed by twelve digits.")).toBeInTheDocument();
    }
    expect(calls(api, "POST", "/admin/watchlist")).toHaveLength(0);
  });

  it("the add row is CNR, Office and Add: no reason or weight; the root is not offered; the lines after saving", async () => {
    let n = 0;
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices/choices": choices([ROOT, EDU, HEALTH]),
      "GET /admin/watchlist": { items: [watch()], total: 1 },
      "POST /admin/watchlist": () =>
        json(201, ++n === 1 ? { ...watch({ id: "w-2", case_ref: null }), dossier_queued: true } : { ...watch({ id: "w-3" }), dossier_queued: false }),
    });
    renderWithClient(<Watchlist />);
    expect(await screen.findByRole("link", { name: "ASLMS/GOA/CASE/2025/000001" })).toHaveAttribute("href", "/search?q=ASLMS%2FGOA%2FCASE%2F2025%2F000001");
    const form = screen.getByRole("form", { name: "Watchlist" });
    expect(within(form).queryByLabelText(/Reason/)).toBeNull();
    expect(within(form).queryByLabelText(/Weight/)).toBeNull();
    await userEvent.click(within(form).getByRole("combobox", { name: "Office" }));
    const list = await screen.findByRole("listbox");
    expect(within(list).queryByText("Government of Assam")).toBeNull();
    await userEvent.click(within(list).getByText("Education"));
    await userEvent.type(within(form).getByLabelText("CNR"), " ashc010099992026 ");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByText(/its court details are queued/)).toBeInTheDocument();
    expect(calls(api, "POST", "/admin/watchlist")[0]!.body).toEqual({ cnr: "ASHC010099992026", office_code: "EDU" });

    await userEvent.type(within(form).getByLabelText("CNR"), "ASHC010012342025");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("The case was scored again now.")).toBeInTheDocument();
    expect(calls(api, "POST", "/admin/watchlist")[1]!.body).toEqual({ cnr: "ASHC010012342025", office_code: null });
    expect(calls(api, "GET", "/admin/offices/choices")[0]!.path).toContain("purpose=watchlist");
  });

  it("shows the API's office_code refusal on the picker; the search narrows the list", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices/choices": choices([EDU, HEALTH]),
      "GET /admin/watchlist": { items: [watch(), watch({ id: "w-9", cnr: "ASHC010099992026", case_ref: null })], total: 2 },
      "POST /admin/watchlist": json(400, { detail: "office_code is required: you work in 2 departments" }),
    });
    renderWithClient(<Watchlist />);
    expectDataTable(await screen.findByRole("table", { name: "Watchlist" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search Watchlist" }), "9999");
    expect(screen.queryByText("ASHC010012342025")).toBeNull();
    expect(screen.getByText("ASHC010099992026")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Watchlist" });
    await userEvent.type(within(form).getByLabelText("CNR"), "ASHC010012342025");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByText("office_code is required: you work in 2 departments")).toBeInTheDocument();
    expect(within(form).getByRole("combobox", { name: "Office" })).toHaveAttribute("aria-invalid", "true");
  });
});

describe("scoring (decisions 40 and 43)", () => {
  function scorer(extra: Record<string, unknown> = {}) {
    return browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": settings(3),
      "GET /admin/scoring-settings/history": { items: [settings(3)], total: 1 },
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/keywords": { items: [], total: 0 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "GET /admin/watchlist": { items: [], total: 0 },
      ...extra,
    });
  }

  it("the slider and the number field of a weight stay in sync", async () => {
    expect(sliderValue("0.43")).toBeCloseTo(0.45);
    expect(sliderValue("0.01")).toBeCloseTo(0.05);
    scorer();
    renderWithClient(<Scoring />);
    const number = await screen.findByRole("spinbutton", { name: "Keyword" });
    const slider = screen.getByRole("slider", { name: "Keyword, slider" });
    expect(slider).toHaveAttribute("min", "0.05");
    expect(slider).toHaveAttribute("step", "0.05");
    expect(number).toHaveAttribute("min", "0.01");
    expect(number).toHaveAttribute("step", "0.01");
    expect(slider).toHaveValue("0.4");
    await userEvent.clear(number);
    await userEvent.type(number, "0.7");
    expect(slider).toHaveValue("0.7");
    // a slider move writes the number
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(slider, { target: { value: "0.55" } });
    expect(number).toHaveValue(0.55);
    expect(screen.getByRole("region", { name: "Unsaved Changes" })).toHaveTextContent("1 unsaved change");
    expect(screen.getByText("Nothing is ever assigned automatically; a department always claims.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /No Recommendation 50%, Possible Match 35%, Strong 15%/ })).toBeInTheDocument();
  });

  it("Save Changes asks for the reason and sends all eight values with the loaded version", async () => {
    const api = scorer({ "PUT /admin/scoring-settings": { ...settings(4), changed: true, rescore_dispatched: true, applies_within_minutes: 15 } });
    renderWithClient(<Scoring />);
    const keywordInput = await screen.findByRole("spinbutton", { name: "Keyword" });
    await userEvent.clear(keywordInput);
    await userEvent.type(keywordInput, "0.45");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    const dialog = await screen.findByRole("dialog", { name: "Save New Scoring Settings" });
    expect(within(dialog).getByText("0.400")).toBeInTheDocument();
    expect(within(dialog).getByText("0.450")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save Changes" }));
    expect(await within(dialog).findByText("A reason is required.")).toBeInTheDocument();
    expect(calls(api, "PUT", "/admin/scoring-settings")).toHaveLength(0);
    await userEvent.type(within(dialog).getByLabelText("Reason for the Change (Required)"), "keywords were too weak");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText(/Saved as version 4\. Recommendations are rescored within 15 minutes; rescoring has started/)).toBeInTheDocument();
    expect(calls(api, "PUT", "/admin/scoring-settings")[0]!.body).toEqual({
      weights: { counsel_code: 0.9, counsel_code_partial: 0.6, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.45 },
      thresholds: { strong: 0.85, possible: 0.5 },
      reason: "keywords were too weak",
      expected_version: 3,
    });
  });

  it("shows six weights with the partial counsel code, and checks its band before saving", async () => {
    const api = scorer();
    renderWithClient(<Scoring />);
    const partial = await screen.findByRole("spinbutton", { name: "Partial Counsel Code" });
    expect(partial).toHaveValue(0.6);
    expect(screen.getByRole("slider", { name: "Partial Counsel Code, slider" })).toBeInTheDocument();
    expect(screen.getAllByRole("slider")).toHaveLength(6);
    expect(screen.getByText(/Stays in the possible band and below the counsel code weight/)).toBeInTheDocument();
    await userEvent.clear(partial);
    await userEvent.type(partial, "0.9");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("The partial code weight must be at least Possible and below Strong.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    const strong = screen.getByLabelText("Strong Recommendation From");
    await userEvent.clear(strong);
    await userEvent.type(strong, "0.99");
    await userEvent.clear(partial);
    await userEvent.type(partial, "0.95");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("The partial code weight must be below the counsel code weight.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls(api, "PUT", "/admin/scoring-settings")).toHaveLength(0);
  });

  it("the history shows a dash for a version written before the partial weight existed", async () => {
    const v1 = settings(1, { valid_to: "2026-10-05T05:00:00Z", weights: { counsel_code: 0.9, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.4 } });
    const v2 = settings(2, { reason: "Partial counsel-code match added (design partial-code-match), partial weight 0.600" });
    scorer({ "GET /admin/scoring-settings": v2, "GET /admin/scoring-settings/history": { items: [v2, v1], total: 2 } });
    renderWithClient(<Scoring />);
    const history = await screen.findByRole("table", { name: "History (2)" });
    const rows = within(history).getAllByRole("row");
    expect(within(history).getByRole("columnheader", { name: "Partial Counsel Code" })).toBeInTheDocument();
    expect(within(rows[2]!).getByText("—", { selector: ".mono" })).toBeInTheDocument();
    expect(within(rows[1]!).getAllByText("(changed)")).toHaveLength(1);
  });

  it("refuses Possible at or above Strong; Discard restores the loaded values", async () => {
    const api = scorer();
    renderWithClient(<Scoring />);
    const possible = await screen.findByLabelText("Possible Match From");
    await userEvent.clear(possible);
    await userEvent.type(possible, "0.85");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("Possible must be below Strong.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(possible).toHaveValue(0.5);
    expect(calls(api, "PUT", "/admin/scoring-settings")).toHaveLength(0);
  });

  it("a stale version re-reads the settings and history, shows the reload line and keeps the reason", async () => {
    let reads = 0;
    const api = scorer({
      "GET /admin/scoring-settings": () => (++reads === 1 ? settings(3) : settings(4, { weights: { ...settings(4).weights, keyword: 0.5 } })),
      "PUT /admin/scoring-settings": json(409, { detail: "the settings changed meanwhile (version 4)" }),
    });
    renderWithClient(<Scoring />);
    const keywordInput = await screen.findByRole("spinbutton", { name: "Keyword" });
    await userEvent.clear(keywordInput);
    await userEvent.type(keywordInput, "0.45");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Reason for the Change (Required)"), "my reason");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save Changes" }));
    expect(await screen.findByText("The settings were changed by someone else and have been reloaded; review them and save again.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Keyword" })).toHaveValue(0.5));
    expect(calls(api, "GET", "/admin/scoring-settings").length).toBeGreaterThanOrEqual(2);
    expect(calls(api, "GET", "/admin/scoring-settings/history").length).toBeGreaterThanOrEqual(2);
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Keyword" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Keyword" }), "0.45");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Reason for the Change (Required)")).toHaveValue("my reason");
  });

  it("Rules with Their Own Weight lists the overrides and Use the Standard Weight sends weight: null", async () => {
    const api = scorer({
      "GET /admin/counsel-codes": { items: [code({ weight_override: 0.7 }), code({ id: "cc-2", code: "SC, HEALTH" })], total: 2 },
      "GET /admin/keywords": { items: [keyword({ weight_override: 0.3 })], total: 1 },
      "PATCH /admin/counsel-codes/cc-1": { ...code(), applies_within_minutes: 15 },
    });
    renderWithClient(<Scoring />);
    const table = await screen.findByRole("table", { name: "Rules with Their Own Weight" });
    expectDataTable(table);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("SC, EDU")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("0.700")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("0.900")).toBeInTheDocument();
    expect(within(table).queryByText("SC, HEALTH")).toBeNull();
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Use the standard weight for SC, EDU" }));
    await waitFor(() => expect(calls(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(1));
    expect(calls(api, "PATCH", "/admin/counsel-codes/cc-1")[0]!.body).toEqual({ weight: null });
  });

  it("says when no rule has its own weight", async () => {
    scorer();
    renderWithClient(<Scoring />);
    expect(await screen.findByText("No rule has its own weight.")).toBeInTheDocument();
  });

  it("is read only without admin.scoring: no save bar, no history, no own-weight panel", async () => {
    const api = browserApi({ "GET /me": deptAdmin(["admin.keywords"]), "GET /admin/scoring-settings": settings(3) });
    renderWithClient(<Scoring />);
    expect(await screen.findByText("Super Admin")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Keyword" })).toHaveAttribute("readonly");
    expect(screen.getByRole("slider", { name: "Keyword, slider" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save Changes" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Unsaved Changes" })).toBeNull();
    expect(screen.queryByText("Rules with Their Own Weight")).toBeNull();
    expect(calls(api, "GET", "/admin/scoring-settings/history")).toHaveLength(0);
    expect(calls(api, "GET", "/admin/keywords")).toHaveLength(0);
  });

  it("version 0 shows the built-in defaults; the history marks changed values", async () => {
    const v2 = settings(2, { valid_to: "2026-10-05T05:00:00Z" });
    const v3 = settings(3, { weights: { ...settings(3).weights, keyword: 0.45 }, reason: "keywords too weak" });
    browserApi({ "GET /me": deptAdmin(["admin.counsel_codes"]), "GET /admin/scoring-settings": settings(0) });
    const { unmount } = renderWithClient(<Scoring />);
    expect(await screen.findByText("Built-in Defaults, Never Saved")).toBeInTheDocument();
    unmount();
    scorer({ "GET /admin/scoring-settings": v3, "GET /admin/scoring-settings/history": { items: [v3, v2], total: 2 } });
    renderWithClient(<Scoring />);
    const history = await screen.findByRole("table", { name: "History (2)" });
    expectDataTable(history);
    const rows = within(history).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getAllByText("(changed)")).toHaveLength(1);
    expect(within(rows[2]!).queryByText("(changed)")).toBeNull();
  });
});

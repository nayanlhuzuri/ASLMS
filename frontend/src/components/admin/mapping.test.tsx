import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type {
  CounselCode,
  Keyword,
  Me,
  OfficeOut,
  Permission,
  ScoringSettings,
  UnmappedCode,
  Watch,
} from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, expectDataTable, json, makeMe, renderWithClient, type BrowserCall } from "@/test/render";

import { CounselCodes } from "./mapping/CounselCodes";
import { KeywordsAndPatterns } from "./mapping/Keywords";
import { Scoring } from "./mapping/Scoring";
import { Watchlist } from "./mapping/Watchlist";

const RULES: Permission[] = ["users.view", "admin.counsel_codes", "admin.keywords", "admin.watchlist"];

function deptAdmin(functions: Permission[] = RULES): Me {
  return makeMe(functions, "dept_admin");
}

function superAdmin(): Me {
  return makeMe([...RULES, "admin.scoring"], "super_admin", {
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

function office(code: string, path: string, kind = "department", name = code): OfficeOut {
  return { id: `o-${code}`, code, name, kind, path, is_active: true };
}

const ROOT = office("GOA", "GOA", "state", "Government of Assam");
const EDU = office("EDU", "GOA/EDU", "department", "Education");
const DSE = office("EDU-DSE", "GOA/EDU/EDU-DSE", "directorate", "Secondary Education");
const HEALTH = office("HEALTH", "GOA/HEALTH", "department", "Health");

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
    weights: { counsel_code: 0.9, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.4 },
    thresholds: { strong: 0.85, possible: 0.5 },
    reason: version === 0 ? null : "initial",
    valid_from: version === 0 ? null : "2026-10-01T05:00:00Z",
    valid_to: null,
    updated_by: version === 0 ? null : { id: "u-0", full_name: "Super Admin" },
    engine_version: "m1",
    ...extra,
  };
}

const posts = (api: { calls: BrowserCall[] }, method: string, path: string) =>
  api.calls.filter((c) => c.method === method && c.path.split("?")[0] === path);

beforeEach(() => {
  resetNav("/admin/mapping/codes");
});

describe("counsel codes", () => {
  it("without admin.scoring: no weight input, and no request carries a weight key", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
      "POST /admin/counsel-codes": json(201, { ...code({ id: "cc-2", code: "SC, DSE" }), applies_within_minutes: 15 }),
      "PATCH /admin/counsel-codes/cc-1": { ...code({ notes: "the main code" }), applies_within_minutes: 15 },
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("SC, EDU")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Weight override/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear override" })).toBeNull();
    expect(screen.getByText("0.900")).toBeInTheDocument();
    expect(screen.getByText("setting")).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Add a counsel code" });
    await userEvent.type(within(form).getByLabelText("Code"), "SC, DSE");
    await userEvent.selectOptions((await within(form).findByLabelText("Office")), "EDU-DSE");
    await userEvent.click(within(form).getByRole("button", { name: "Add a counsel code" }));
    expect(await screen.findByText("Takes effect at the next rescore, within 15 minutes.")).toBeInTheDocument();
    const create = posts(api, "POST", "/admin/counsel-codes")[0]!.body as Record<string, unknown>;
    expect(create).toEqual({ code: "SC, DSE", office_code: "EDU-DSE", is_generic_state: false, notes: null });
    expect("weight" in create).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Edit SC, EDU" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/Weight override/)).toBeNull();
    await userEvent.type(within(dialog).getByLabelText("Notes"), "the main code");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(1));
    expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")[0]!.body).toEqual({ notes: "the main code" });
  });

  it("with admin.scoring: an unchanged override is not sent and a cleared one sends null", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices": [ROOT, EDU, HEALTH],
      "GET /admin/counsel-codes": { items: [code({ weight_override: 0.7, effective_weight: 0.7 })], total: 1 },
      "PATCH /admin/counsel-codes/cc-1": { ...code(), applies_within_minutes: 15 },
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("override")).toBeInTheDocument();
    expect(screen.getByLabelText(/Weight override/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Edit SC, EDU" }));
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Weight override/)).toHaveValue(0.7);
    await userEvent.type(within(dialog).getByLabelText("Notes"), "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(1));
    expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")[0]!.body).toEqual({ notes: "x" });

    await userEvent.click(await screen.findByRole("button", { name: "Edit SC, EDU" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear override" }));
    expect(within(dialog).getByText("The override will be cleared when you save.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(2));
    expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")[1]!.body).toEqual({ weight: null });
  });

  it("the root office makes the code generic; any other office does not", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices": [ROOT, EDU, HEALTH],
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "POST /admin/counsel-codes": json(201, { ...code({ code: "PP, ASSAM" }), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    const form = await screen.findByRole("form", { name: "Add a counsel code" });
    await userEvent.type(within(form).getByLabelText("Code"), "PP, ASSAM");
    await userEvent.selectOptions((await within(form).findByLabelText("Office")), "GOA");
    expect(within(form).getByText(/A code mapped to the State is generic/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Add a counsel code" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/counsel-codes")).toHaveLength(1));
    expect(posts(api, "POST", "/admin/counsel-codes")[0]!.body).toMatchObject({ office_code: "GOA", is_generic_state: true });

    await userEvent.type(within(form).getByLabelText("Code"), "SC, HEALTH");
    await userEvent.selectOptions((await within(form).findByLabelText("Office")), "HEALTH");
    expect(within(form).queryByText(/A code mapped to the State is generic/)).toBeNull();
    await userEvent.click(within(form).getByRole("button", { name: "Add a counsel code" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/counsel-codes")).toHaveLength(2));
    expect(posts(api, "POST", "/admin/counsel-codes")[1]!.body).toMatchObject({ office_code: "HEALTH", is_generic_state: false });
  });

  it("generic rows show no actions when the root office is not in the picker", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": {
        items: [code(), code({ id: "cc-9", code: "PP, ASSAM", is_generic_state: true, office: { code: "GOA", name: "Government of Assam" } })],
        total: 2,
      },
    });
    renderWithClient(<CounselCodes />);
    expect(await screen.findByText("PP, ASSAM")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit SC, EDU" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit PP, ASSAM" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deactivate PP, ASSAM" })).toBeNull();
  });

  it("the office picker lists /admin/offices with users.view and is a text field without it", async () => {
    let api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": { items: [], total: 0 },
    });
    const first = renderWithClient(<CounselCodes />);
    const form = await screen.findByRole("form", { name: "Add a counsel code" });
    const select = (await within(form).findByLabelText("Office"));
    await waitFor(() => expect(within(select).getByRole("option", { name: /Secondary Education \(EDU-DSE\)/ })).toBeInTheDocument());
    expect(within(select).getByRole("option", { name: /Education \(EDU\)/ })).toBeInTheDocument();
    first.unmount();

    api = browserApi({
      "GET /me": deptAdmin(["admin.counsel_codes"]),
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "POST /admin/counsel-codes": json(201, { ...code(), applies_within_minutes: 15 }),
    });
    renderWithClient(<CounselCodes />);
    const form2 = await screen.findByRole("form", { name: "Add a counsel code" });
    const typed = await within(form2).findByLabelText("Office code");
    expect(typed.tagName).toBe("INPUT");
    await userEvent.type(within(form2).getByLabelText("Code"), "SC, EDU");
    await userEvent.type(typed, "edu");
    await userEvent.click(within(form2).getByRole("button", { name: "Add a counsel code" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/counsel-codes")).toHaveLength(1));
    expect(posts(api, "POST", "/admin/counsel-codes")[0]!.body).toMatchObject({ office_code: "EDU", is_generic_state: false });
    expect(posts(api, "GET", "/admin/offices")).toHaveLength(0);
  });

  it("the unmapped panel is read only when opened; Map fills the form and sends nothing", async () => {
    const unmapped: UnmappedCode[] = [
      { code: "SC, PWD", entries: 1240, last_listed: "2026-10-09", example_case_ref: "ASLMS/GOA/CASE/2026/000042" },
    ];
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": unmapped,
    });
    renderWithClient(<CounselCodes />);
    await screen.findByText("Nothing here yet.");
    expect(posts(api, "GET", "/admin/counsel-codes/unmapped")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Show codes seen in cause lists but not mapped" }));
    expect(await screen.findByText("SC, PWD")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is mapped automatically/)).toBeInTheDocument();
    expect(posts(api, "GET", "/admin/counsel-codes/unmapped")[0]!.url).toContain("limit=100");
    expect(screen.getByRole("link", { name: "ASLMS/GOA/CASE/2026/000042" })).toHaveAttribute(
      "href",
      "/search?q=ASLMS%2FGOA%2FCASE%2F2026%2F000042",
    );
    await userEvent.click(screen.getByRole("button", { name: "Map SC, PWD" }));
    const form = screen.getByRole("form", { name: "Add a counsel code" });
    expect(within(form).getByLabelText("Code")).toHaveValue("SC, PWD");
    expect((await within(form).findByLabelText("Office"))).toHaveFocus();
    expect(api.calls.filter((c) => c.method !== "GET")).toHaveLength(0);
  });

  it("a failing unmapped report shows the API's message with Retry", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU],
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "GET /admin/counsel-codes/unmapped": json(503, { detail: "the report took too long" }),
    });
    renderWithClient(<CounselCodes />);
    await userEvent.click(await screen.findByRole("button", { name: "Show codes seen in cause lists but not mapped" }));
    expect(await screen.findByText("the report took too long")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("keywords and name patterns", () => {
  it("offer no Edit without admin.scoring; Deactivate asks first and posts", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": { items: [keyword()], total: 1 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "POST /admin/keywords/kw-1/deactivate": { ...keyword({ is_active: false }), applies_within_minutes: 15 },
    });
    renderWithClient(<KeywordsAndPatterns />);
    expect(await screen.findByText("DIRECTOR OF SECONDARY EDUCATION")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(screen.queryByLabelText(/Weight override/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Deactivate DIRECTOR OF SECONDARY EDUCATION" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/stops counting at the next rescore, within 15 minutes/)).toBeInTheDocument();
    expect(posts(api, "POST", "/admin/keywords/kw-1/deactivate")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/keywords/kw-1/deactivate")).toHaveLength(1));
    expect(await screen.findByText("Takes effect at the next rescore, within 15 minutes.")).toBeInTheDocument();
  });

  it("with admin.scoring a keyword's Edit sends only the weight", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices": [ROOT, EDU],
      "GET /admin/keywords": { items: [keyword()], total: 1 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "PATCH /admin/keywords/kw-1": { ...keyword({ weight_override: 0.45 }), applies_within_minutes: 15 },
    });
    renderWithClient(<KeywordsAndPatterns />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit DIRECTOR OF SECONDARY EDUCATION" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Weight override/), "0.45");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/keywords/kw-1")).toHaveLength(1));
    expect(posts(api, "PATCH", "/admin/keywords/kw-1")[0]!.body).toEqual({ weight: 0.45 });
  });

  it("a rule save says when it applies; a 409 shows the API's message and re-reads the list", async () => {
    let n = 0;
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": { items: [], total: 0 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "POST /admin/keywords": () =>
        ++n === 1
          ? json(201, { ...keyword({ id: "kw-2", keyword: "COMMISSIONER OF EDUCATION" }), applies_within_minutes: 15 })
          : json(409, { detail: "the keyword COMMISSIONER OF EDUCATION already exists for EDU" }),
      "POST /admin/name-patterns": json(201, {
        id: "np-1",
        pattern: "STATE OF ASSAM",
        kind: "prefix",
        office: { code: "EDU", name: "Education" },
        weight_override: null,
        effective_weight: 0.6,
        is_active: true,
        updated_at: "2026-10-10T05:00:00Z",
        applies_within_minutes: 15,
      }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    const form = await screen.findByRole("form", { name: "Add a keyword" });
    await userEvent.type(within(form).getByLabelText("Keyword"), "COMMISSIONER OF EDUCATION");
    await userEvent.selectOptions((await within(form).findByLabelText("Office")), "EDU");
    await userEvent.click(within(form).getByRole("button", { name: "Add a keyword" }));
    expect(await screen.findByText("Takes effect at the next rescore, within 15 minutes.")).toBeInTheDocument();
    expect(posts(api, "POST", "/admin/keywords")[0]!.body).toEqual({ keyword: "COMMISSIONER OF EDUCATION", office_code: "EDU" });

    const before = posts(api, "GET", "/admin/keywords").length;
    await userEvent.type(within(form).getByLabelText("Keyword"), "COMMISSIONER OF EDUCATION");
    await userEvent.selectOptions((await within(form).findByLabelText("Office")), "EDU");
    await userEvent.click(within(form).getByRole("button", { name: "Add a keyword" }));
    expect(await screen.findByText("the keyword COMMISSIONER OF EDUCATION already exists for EDU")).toBeInTheDocument();
    await waitFor(() => expect(posts(api, "GET", "/admin/keywords").length).toBeGreaterThan(before));

    const pform = screen.getByRole("form", { name: "Add a name pattern" });
    await userEvent.type(within(pform).getByLabelText("Pattern"), "STATE OF ASSAM");
    await userEvent.selectOptions(within(pform).getByLabelText("Kind"), "prefix");
    await userEvent.selectOptions((await within(pform).findByLabelText("Office")), "EDU");
    await userEvent.click(within(pform).getByRole("button", { name: "Add a name pattern" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/name-patterns")).toHaveLength(1));
    expect(posts(api, "POST", "/admin/name-patterns")[0]!.body).toEqual({ pattern: "STATE OF ASSAM", kind: "prefix", office_code: "EDU" });
  });
});

describe("Search the court (department-discovery)", () => {
  it("the add forms pre-tick it for a discoverable text, untick it for others and disable it for a regex", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": { items: [], total: 0 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "POST /admin/name-patterns": json(201, { id: "np-1", pattern: "PRITAM", kind: "prefix", office: { code: "EDU", name: "Education" }, weight_override: null, effective_weight: 0.8, is_active: true, updated_at: "2026-10-10T05:00:00Z", discover: false, discoverable: true, discovery: null, applies_within_minutes: 15 }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    const kform = await screen.findByRole("form", { name: "Add a keyword" });
    const kbox = within(kform).getByLabelText("Search the court");
    await userEvent.type(within(kform).getByLabelText("Keyword"), "Dr. Pritam Saikia");
    expect(kbox).toBeChecked();
    await userEvent.clear(within(kform).getByLabelText("Keyword"));
    await userEvent.type(within(kform).getByLabelText("Keyword"), "100% pass");
    expect(kbox).not.toBeChecked();

    const pform = screen.getByRole("form", { name: "Add a name pattern" });
    const pbox = within(pform).getByLabelText("Search the court");
    await userEvent.type(within(pform).getByLabelText("Pattern"), "PRITAM");
    expect(pbox).toBeChecked();
    expect(pbox).not.toBeDisabled();
    await userEvent.selectOptions(within(pform).getByLabelText("Kind"), "regex");
    expect(pbox).not.toBeChecked();
    expect(pbox).toBeDisabled();
    await userEvent.selectOptions(within(pform).getByLabelText("Kind"), "prefix");
    await userEvent.click(pbox); // the user unticks it: sent as false
    await userEvent.selectOptions((await within(pform).findByLabelText("Office")), "EDU");
    await userEvent.click(within(pform).getByRole("button", { name: "Add a name pattern" }));
    await waitFor(() => expect(posts(api, "POST", "/admin/name-patterns")).toHaveLength(1));
    expect(posts(api, "POST", "/admin/name-patterns")[0]!.body).toEqual({
      pattern: "PRITAM",
      kind: "prefix",
      office_code: "EDU",
      discover: false,
    });
  });

  it("the row toggle sends PATCH {discover}, shows the last search and the refusal", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": {
        items: [
          keyword({ discovery: { term_id: "t-1", last_searched_at: "2026-10-13T05:00:00Z", cases_found: 4 } }),
          keyword({ id: "kw-2", keyword: "100% PASS", discover: false, discoverable: false }),
        ],
        total: 2,
      },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "PATCH /admin/keywords/kw-1": { ...keyword({ discover: false }), applies_within_minutes: 15 },
      "PATCH /admin/keywords/kw-2": json(400, {
        detail: { code: "not_discoverable", message: "only 3 to 200 letters, digits, spaces and . , ' & ( ) / - can be searched at the court" },
      }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    expect(await screen.findByText(/4 case\(s\) found/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Search the court for DIRECTOR OF SECONDARY EDUCATION"));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/keywords/kw-1")).toHaveLength(1));
    expect(posts(api, "PATCH", "/admin/keywords/kw-1")[0]!.body).toEqual({ discover: false });
    await userEvent.click(screen.getByLabelText("Search the court for 100% PASS"));
    await waitFor(() => expect(posts(api, "PATCH", "/admin/keywords/kw-2")).toHaveLength(1));
    expect(posts(api, "PATCH", "/admin/keywords/kw-2")[0]!.body).toEqual({ discover: true });
    expect(await screen.findByText(/can be searched at the court/)).toBeInTheDocument();
  });
});

describe("watchlist", () => {
  it("refuses a malformed CNR without calling the API", async () => {
    const api = browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/watchlist": { items: [], total: 0 },
    });
    renderWithClient(<Watchlist />);
    const form = await screen.findByRole("form", { name: "Add to the watchlist" });
    for (const bad of ["ASHC01001234202", "AS1C010012342025", "ASHC01001234202X"]) {
      await userEvent.clear(within(form).getByLabelText("CNR"));
      await userEvent.type(within(form).getByLabelText("CNR"), bad);
      await userEvent.click(within(form).getByRole("button", { name: "Add to the watchlist" }));
      expect(await within(form).findByText("A CNR is four letters followed by twelve digits.")).toBeInTheDocument();
    }
    expect(posts(api, "POST", "/admin/watchlist")).toHaveLength(0);
  });

  it("shows the queued and the scored lines; the case links through search; the root is not offered", async () => {
    let n = 0;
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices": [ROOT, EDU, HEALTH],
      "GET /admin/watchlist": { items: [watch()], total: 1 },
      "POST /admin/watchlist": () =>
        json(201, ++n === 1 ? { ...watch({ id: "w-2", case_ref: null }), dossier_queued: true } : { ...watch({ id: "w-3" }), dossier_queued: false }),
    });
    renderWithClient(<Watchlist />);
    expect(await screen.findByRole("link", { name: "ASLMS/GOA/CASE/2025/000001" })).toHaveAttribute(
      "href",
      "/search?q=ASLMS%2FGOA%2FCASE%2F2025%2F000001",
    );
    const form = screen.getByRole("form", { name: "Add to the watchlist" });
    const picker = (await within(form).findByLabelText("Office"));
    await waitFor(() => expect(within(picker).getByRole("option", { name: /Health \(HEALTH\)/ })).toBeInTheDocument());
    expect(within(picker).queryByRole("option", { name: /GOA/ })).toBeNull();

    await userEvent.type(within(form).getByLabelText("CNR"), " ashc010099992026 ");
    await userEvent.selectOptions(picker, "EDU");
    await userEvent.click(within(form).getByRole("button", { name: "Add to the watchlist" }));
    expect(await screen.findByText(/its court details are queued/)).toBeInTheDocument();
    expect(posts(api, "POST", "/admin/watchlist")[0]!.body).toEqual({ cnr: "ASHC010099992026", office_code: "EDU", reason: null });

    await userEvent.type(within(form).getByLabelText("CNR"), "ASHC010012342025");
    await userEvent.click(within(form).getByRole("button", { name: "Add to the watchlist" }));
    expect(await screen.findByText("The case was scored again now.")).toBeInTheDocument();
    expect(posts(api, "POST", "/admin/watchlist")[1]!.body).toEqual({ cnr: "ASHC010012342025", office_code: null, reason: null });
  });

  it("shows the API's office_code refusal as given", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, HEALTH],
      "GET /admin/watchlist": { items: [], total: 0 },
      "POST /admin/watchlist": json(400, { detail: "office_code is required: you work in 2 departments" }),
    });
    renderWithClient(<Watchlist />);
    const form = await screen.findByRole("form", { name: "Add to the watchlist" });
    await userEvent.type(within(form).getByLabelText("CNR"), "ASHC010012342025");
    await userEvent.click(within(form).getByRole("button", { name: "Add to the watchlist" }));
    const lines = await screen.findAllByText("office_code is required: you work in 2 departments");
    expect(lines.length).toBeGreaterThanOrEqual(1);
    expect((await within(form).findByLabelText("Office"))).toHaveAttribute("aria-invalid", "true");
  });
});

describe("scoring", () => {
  it("is read-only for admin.keywords without admin.scoring: no inputs, no history request", async () => {
    const api = browserApi({ "GET /me": deptAdmin(["admin.keywords"]), "GET /admin/scoring-settings": settings(3) });
    renderWithClient(<Scoring />);
    expect(await screen.findByText("Super Admin")).toBeInTheDocument();
    expect(screen.getByText("0.850")).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(posts(api, "GET", "/admin/scoring-settings/history")).toHaveLength(0);
  });

  it("version 0 shows the built-in defaults", async () => {
    browserApi({ "GET /me": deptAdmin(["admin.counsel_codes"]), "GET /admin/scoring-settings": settings(0) });
    renderWithClient(<Scoring />);
    expect(await screen.findByText("Built-in defaults, never saved")).toBeInTheDocument();
  });

  it("saves all seven values, the reason and the loaded version after a confirmation", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": settings(3),
      "GET /admin/scoring-settings/history": { items: [settings(3)], total: 1 },
      "PUT /admin/scoring-settings": { ...settings(4), changed: true, rescore_dispatched: true, applies_within_minutes: 15 },
    });
    renderWithClient(<Scoring />);
    const keywordInput = await screen.findByLabelText("Keyword");
    await userEvent.clear(keywordInput);
    await userEvent.type(keywordInput, "0.45");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("A reason is required.")).toBeInTheDocument();
    expect(posts(api, "PUT", "/admin/scoring-settings")).toHaveLength(0);

    await userEvent.type(screen.getByLabelText("Reason for the change (required)"), "keywords were too weak");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("0.400")).toBeInTheDocument();
    expect(within(dialog).getByText("0.450")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved as version 4\. Recommendations are rescored within 15 minutes; rescoring has started/)).toBeInTheDocument();
    expect(posts(api, "PUT", "/admin/scoring-settings")[0]!.body).toEqual({
      weights: { counsel_code: 0.9, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.45 },
      thresholds: { strong: 0.85, possible: 0.5 },
      reason: "keywords were too weak",
      expected_version: 3,
    });
  });

  it("refuses Possible at or above Strong without calling the API", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": settings(3),
      "GET /admin/scoring-settings/history": { items: [settings(3)], total: 1 },
    });
    renderWithClient(<Scoring />);
    const possible = await screen.findByLabelText("Possible");
    await userEvent.clear(possible);
    await userEvent.type(possible, "0.85");
    await userEvent.type(screen.getByLabelText("Reason for the change (required)"), "test");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Possible must be below Strong.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(api, "PUT", "/admin/scoring-settings")).toHaveLength(0);
  });

  it("an unchanged save says nothing changed", async () => {
    browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": settings(3),
      "GET /admin/scoring-settings/history": { items: [settings(3)], total: 1 },
      "PUT /admin/scoring-settings": { ...settings(3), changed: false, rescore_dispatched: false, applies_within_minutes: 15 },
    });
    renderWithClient(<Scoring />);
    await userEvent.type(await screen.findByLabelText("Reason for the change (required)"), "check");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Nothing changed; no new version was saved.")).toBeInTheDocument();
  });

  it("a stale version re-reads the settings and history, shows the reload line and keeps the reason", async () => {
    let reads = 0;
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": () => (++reads === 1 ? settings(3) : settings(4, { weights: { ...settings(4).weights, keyword: 0.5 } })),
      "GET /admin/scoring-settings/history": { items: [settings(3)], total: 1 },
      "PUT /admin/scoring-settings": json(409, { detail: "the settings changed meanwhile (version 4)" }),
    });
    renderWithClient(<Scoring />);
    await userEvent.type(await screen.findByLabelText("Reason for the change (required)"), "my reason");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("The settings were changed by someone else and have been reloaded; review them and save again."),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Keyword")).toHaveValue(0.5));
    expect(screen.getByLabelText("Reason for the change (required)")).toHaveValue("my reason");
    expect(posts(api, "GET", "/admin/scoring-settings").length).toBeGreaterThanOrEqual(2);
    expect(posts(api, "GET", "/admin/scoring-settings/history").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the history lists versions with the total and marks changed values", async () => {
    const v2 = settings(2, { valid_to: "2026-10-05T05:00:00Z" });
    const v3 = settings(3, { weights: { ...settings(3).weights, keyword: 0.45 }, reason: "keywords too weak" });
    browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": v3,
      "GET /admin/scoring-settings/history": { items: [v3, v2], total: 2 },
    });
    renderWithClient(<Scoring />);
    const history = await screen.findByRole("table", { name: "History (2)" });
    const rows = within(history).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText("(changed)")).toBeInTheDocument();
    expect(within(rows[1]!).getAllByText("(changed)")).toHaveLength(1);
    expect(within(rows[2]!).queryByText("(changed)")).toBeNull();
    expect(within(rows[1]!).getByText("keywords too weak")).toBeInTheDocument();
  });
});

describe("tester additions", () => {
  it("an edit dialog with nothing changed closes without a call", async () => {
    const api = browserApi({
      "GET /me": superAdmin(),
      "GET /admin/offices": [ROOT, EDU],
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
    });
    renderWithClient(<CounselCodes />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit SC, EDU" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts(api, "PATCH", "/admin/counsel-codes/cc-1")).toHaveLength(0);
  });

  it("a refused regular expression shows the API's reason", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": { items: [], total: 0 },
      "GET /admin/name-patterns": { items: [], total: 0 },
      "POST /admin/name-patterns": json(400, { detail: "the regular expression is not valid: unterminated group" }),
    });
    renderWithClient(<KeywordsAndPatterns />);
    const pform = await screen.findByRole("form", { name: "Add a name pattern" });
    await userEvent.type(within(pform).getByLabelText("Pattern"), "(abc");
    await userEvent.selectOptions(within(pform).getByLabelText("Kind"), "regex");
    await userEvent.selectOptions(await within(pform).findByLabelText("Office"), "EDU");
    await userEvent.click(within(pform).getByRole("button", { name: "Add a name pattern" }));
    expect((await screen.findAllByText("the regular expression is not valid: unterminated group")).length).toBeGreaterThanOrEqual(1);
  });

  it("a 403 on adding a code shows the server's message, not the generic one", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": { items: [], total: 0 },
      "POST /admin/counsel-codes": json(403, { detail: "the office is outside your offices" }),
    });
    renderWithClient(<CounselCodes />);
    const form = await screen.findByRole("form", { name: "Add a counsel code" });
    await userEvent.type(within(form).getByLabelText(/^Code/), "SC, EDU");
    await userEvent.selectOptions(await within(form).findByLabelText("Office"), "EDU");
    await userEvent.click(within(form).getByRole("button", { name: "Add a counsel code" }));
    expect((await screen.findAllByText("the office is outside your offices")).length).toBeGreaterThanOrEqual(1);
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("CounselCodes renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/counsel-codes": { items: [code()], total: 1 },
      "GET /admin/counsel-codes/unmapped": [
        { code: "SC, PWD", entries: 124000, last_listed: "2026-10-09", example_case_ref: "ASLMS/GOA/CASE/2026/000042" },
      ],
    });
    renderWithClient(<CounselCodes />);
    expectDataTable(await screen.findByRole("table", { name: "Counsel codes" }));
    await userEvent.click(screen.getByRole("button", { name: "Show codes seen in cause lists but not mapped" }));
    expectDataTable(await screen.findByRole("table", { name: "Codes seen in cause lists but not mapped" }));
  });

  it("Keywords renders a DataTable with a primary cell", async () => {
    browserApi({
      "GET /me": deptAdmin(),
      "GET /admin/offices": [EDU, DSE],
      "GET /admin/keywords": { items: [keyword()], total: 1 },
      "GET /admin/name-patterns": {
        items: [
          {
            id: "np-1",
            pattern: "DIRECTOR.*EDUCATION",
            kind: "regex",
            office: { code: "EDU", name: "Education" },
            weight_override: null,
            effective_weight: 0.6,
            discover: false,
            discoverable: false,
            is_active: true,
            updated_at: "2026-10-01T05:00:00Z",
          },
        ],
        total: 1,
      },
    });
    renderWithClient(<KeywordsAndPatterns />);
    expectDataTable(await screen.findByRole("table", { name: "Keywords" }));
    expectDataTable(await screen.findByRole("table", { name: "Name patterns" }));
  });

  it("Watchlist renders a DataTable with a primary cell", async () => {
    browserApi({ "GET /me": superAdmin(), "GET /admin/offices": [ROOT, EDU, HEALTH], "GET /admin/watchlist": { items: [watch()], total: 1 } });
    renderWithClient(<Watchlist />);
    expectDataTable(await screen.findByRole("table", { name: "Watchlist" }));
  });

  it("Scoring renders a DataTable with a primary cell", async () => {
    browserApi({ "GET /me": deptAdmin(["admin.keywords"]), "GET /admin/scoring-settings": settings(3) });
    const { unmount } = renderWithClient(<Scoring />);
    const values = expectDataTable(await screen.findByRole("table", { name: "Weights and thresholds" }));
    expect(within(values).getAllByRole("rowheader").length).toBeGreaterThan(0);
    unmount();
    browserApi({
      "GET /me": superAdmin(),
      "GET /admin/scoring-settings": settings(3),
      "GET /admin/scoring-settings/history": { items: [settings(3), settings(2)], total: 2 },
    });
    renderWithClient(<Scoring />);
    expectDataTable(await screen.findByRole("table", { name: "History (2)" }));
  });
});

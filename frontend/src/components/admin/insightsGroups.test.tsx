import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { InsightCaseType, InsightCategory, InsightGroup } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, renderWithClient, toastStatus } from "@/test/render";

import { changesOf, InsightsGroups, tabOf } from "./InsightsGroups";

function group(code: string, label: string, extra: Partial<InsightGroup> = {}): InsightGroup {
  return {
    id: `g-${code}`,
    kind: "subject",
    code,
    label,
    description: null,
    sort_order: 10,
    is_reserved: false,
    is_active: true,
    members: 3,
    cases: 40,
    pending: 20,
    ...extra,
  };
}

const SUBJECT_GROUPS: InsightGroup[] = [
  group("service_state", "Service: State Government Employees"),
  group("land", "Land and Revenue", { is_active: false }),
  group("contempt", "Contempt (Original Subject Not Yet Known)", { is_reserved: true }),
];

const CATEGORIES: InsightCategory[] = [
  { code: 10245, label: "Service Matters - Pay", group: "service_state", cases: 30, pending: 12 },
  { code: 20240, label: "Land Acquisition", group: null, cases: 5, pending: 2 },
];

const FAMILY_GROUPS: InsightGroup[] = [
  group("wp", "Writ Petition", { kind: "family" }),
  group("ia", "Interlocutory Application", { kind: "family", is_reserved: true }),
  group("other", "Other", { kind: "family", is_reserved: true }),
];

const CASE_TYPES: InsightCaseType[] = [
  { id: "ct-1", code: 111, name: "WP(C)", full_name: "Writ Petition (Civil)", group: "wp", cases: 70, pending: 30 },
  { id: "ct-2", code: 159, name: "MC", full_name: null, group: "other", cases: 4, pending: 1 },
];

beforeEach(() => resetNav("/admin/insights-groups"));

describe("Insights Groups (design state-insights, decision 34)", () => {
  it("saves the changed lines in one batch with a toast", async () => {
    const api = browserApi({
      "GET /admin/insights/groups": SUBJECT_GROUPS,
      "GET /admin/insights/categories": CATEGORIES,
      "PUT /admin/insights/categories": [{ ...CATEGORIES[1], group: "service_state" }],
    });
    renderWithClient(<InsightsGroups params={{}} />);
    const save = await screen.findByRole("button", { name: "Save Changes" });
    expect(save).toBeDisabled();
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Group for Land Acquisition" }), "service_state");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group for Service Matters - Pay" }), "");
    expect(screen.getByText("2 changes not yet saved.")).toBeInTheDocument();
    await userEvent.click(save);
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = api.calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({
      changes: [
        { code: 10245, group: null },
        { code: 20240, group: "service_state" },
      ],
    });
    await waitFor(() => expect(toastStatus()).toHaveTextContent("Saved 2 changes. They are in the audit log."));
  });

  it("locks the reserved groups: no Turn Off, only Edit; a turned-off group is not offered", async () => {
    browserApi({ "GET /admin/insights/groups": SUBJECT_GROUPS, "GET /admin/insights/categories": CATEGORIES });
    renderWithClient(<InsightsGroups params={{}} />);
    const table = await screen.findByRole("table", { name: "Groups" });
    const reserved = within(table).getByRole("rowheader", { name: "Contempt (Original Subject Not Yet Known)" }).closest("tr")!;
    expect(within(reserved).getByText("Reserved")).toBeInTheDocument();
    expect(within(reserved).queryByRole("button", { name: "Turn Off" })).toBeNull();
    expect(within(reserved).getByRole("button", { name: /^Edit / })).toBeInTheDocument();
    const off = within(table).getByRole("rowheader", { name: "Land and Revenue" }).closest("tr")!;
    expect(within(off).getByRole("button", { name: "Turn On" })).toBeInTheDocument();
    const select = await screen.findByRole("combobox", { name: "Group for Land Acquisition" });
    expect(within(select).queryByRole("option", { name: "Land and Revenue" })).toBeNull();
    expect(within(select).getByRole("option", { name: "Not Grouped" })).toBeInTheDocument();
  });

  it("Not Grouped Only and Search narrow the lines", async () => {
    browserApi({ "GET /admin/insights/groups": SUBJECT_GROUPS, "GET /admin/insights/categories": CATEGORIES });
    renderWithClient(<InsightsGroups params={{}} />);
    await screen.findByRole("combobox", { name: "Group for Land Acquisition" });
    await userEvent.click(screen.getByRole("switch", { name: "Not Grouped Only" }));
    expect(screen.queryByRole("combobox", { name: "Group for Service Matters - Pay" })).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Not Grouped Only" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search" }), "10245");
    expect(screen.queryByRole("combobox", { name: "Group for Land Acquisition" })).toBeNull();
  });

  it("adds a group and refuses a taken code with the server's reason", async () => {
    const api = browserApi({
      "GET /admin/insights/groups": SUBJECT_GROUPS,
      "GET /admin/insights/categories": CATEGORIES,
      "POST /admin/insights/groups": json(409, { detail: { code: "code_taken", message: "taken" } }),
    });
    renderWithClient(<InsightsGroups params={{}} />);
    const form = await screen.findByRole("form", { name: "Add a Group" });
    await userEvent.type(within(form).getByRole("textbox", { name: /Code/ }), "service_state");
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Again");
    await userEvent.click(within(form).getByRole("button", { name: "Add Group" }));
    expect(await screen.findByText("Another group already has this code.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ kind: "subject", code: "service_state", label: "Again" });
  });

  it("the Kinds of Case tab sends case-type ids; Other is the fallback", async () => {
    const api = browserApi({
      "GET /admin/insights/groups": FAMILY_GROUPS,
      "GET /admin/insights/case-types": CASE_TYPES,
      "PUT /admin/insights/case-types": [],
    });
    renderWithClient(<InsightsGroups params={{ tab: "family" }} />);
    expect(screen.getByRole("link", { name: "Kinds of Case" })).toHaveAttribute("aria-current", "page");
    const select = await screen.findByRole("combobox", { name: "Group for MC" });
    expect(within(select).queryByRole("option", { name: "Not Grouped" })).toBeNull();
    await userEvent.selectOptions(select, "wp");
    await userEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({ changes: [{ case_type_id: "ct-2", group: "wp" }] });
    expect(api.calls.find((c) => c.path.startsWith("/admin/insights/groups"))!.path).toBe("/admin/insights/groups?kind=family");
  });

  it("says who may group when the API refuses", async () => {
    browserApi({ "GET /admin/insights/groups": json(403, { detail: { code: "forbidden", message: "no" } }) });
    renderWithClient(<InsightsGroups params={{}} />);
    expect(await screen.findByText("Only the Super Administrator groups the court's categories and case types.")).toBeInTheDocument();
  });

  it("the pure rules", () => {
    expect(tabOf({ tab: "family" })).toBe("family");
    expect(tabOf({})).toBe("subject");
    const members = [{ key: "1", code: 1, label: "A", group: "x", cases: 0, pending: 0 }];
    expect(changesOf("subject", { "1": "x" }, members)).toEqual({ changes: [] });
    expect(changesOf("subject", { "1": "" }, members)).toEqual({ changes: [{ code: 1, group: null }] });
  });
});

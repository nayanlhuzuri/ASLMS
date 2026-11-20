import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { OfficeChoice, TitleName } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, renderWithClient, type BrowserCall } from "@/test/render";

import { TitleNames } from "./mapping/TitleNames";

function name(id: string, phrase: string, extra: Partial<TitleName> = {}): TitleName {
  return { id, phrase, office_code: "EDU", office_name: "School Education", department_code: "EDU", is_active: true, cases: 12, ...extra };
}

const EDU: OfficeChoice = {
  code: "EDU",
  name: "School Education",
  kind: "department",
  tier: "department",
  depth: 1,
  parent_code: "GOA",
  ancestors: ["Government of Assam"],
  is_active: true,
};

function routes(extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /admin/title-names": (call: BrowserCall) => {
      const active = new URL(call.path, "http://x").searchParams.get("active");
      return active === "false"
        ? { items: [name("t-9", "OLD EDUCATION", { is_active: false, cases: 0 })], total: 1 }
        : { items: [name("t-1", "EDUCATION (SECONDARY)"), name("t-2", "SCHOOL EDUCATION", { cases: 40 })], total: 2 };
    },
    "GET /admin/title-names/unmapped": {
      items: [
        { phrase: "FINANCE (TAXATION)", cases: 9, example_case_no: "WP(C)/12/2026" },
        { phrase: "REVENUE AND DISASTER MANAGEMENT", cases: 4, example_case_no: null },
      ],
      total: 2,
    },
    "GET /admin/offices/choices": { purpose: "keywords", items: [EDU] },
    ...extra,
  });
}

beforeEach(() => resetNav("/admin/mapping/title-names"));

describe("Names in Cause Titles (design state-insights, decision 35)", () => {
  it("lists the mapped names with their office and cases, and adds the deactivated ones on request", async () => {
    const api = routes();
    renderWithClient(<TitleNames />);
    const table = await screen.findByRole("table", { name: "Names in Cause Titles" });
    expect(within(table).getByText("EDUCATION (SECONDARY)")).toBeInTheDocument();
    expect(within(table).getByText("SCHOOL EDUCATION").closest("tr")).toHaveTextContent("40");
    expect(within(table).queryByText("OLD EDUCATION")).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Include Deactivated" }));
    expect(await screen.findByText("OLD EDUCATION")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path.startsWith("/admin/title-names?")).map((c) => c.path)).toEqual([
      "/admin/title-names?active=true",
      "/admin/title-names?active=false",
    ]);
  });

  it("the Unmapped Names panel lists phrases with cases and an example; Map puts the phrase in the add form", async () => {
    routes();
    renderWithClient(<TitleNames />);
    const panel = await screen.findByRole("complementary", { name: "Unmapped Names" });
    const row = (await within(panel).findByText("FINANCE (TAXATION)")).closest("tr")!;
    expect(row).toHaveTextContent("9");
    expect(within(row).getByRole("link", { name: "WP(C)/12/2026" })).toHaveAttribute("href", "/search?q=WP(C)%2F12%2F2026");
    expect(within(panel).getByText("2 names not mapped")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Map FINANCE (TAXATION)" }));
    const form = screen.getByRole("form", { name: "Add a Name" });
    expect(within(form).getByRole("textbox", { name: "Printed Name" })).toHaveValue("FINANCE (TAXATION)");
  });

  it("adds a name with its office; a refused phrase shows the rule", async () => {
    const api = routes({
      "POST /admin/title-names": json(400, { detail: { code: "bad_phrase", message: "bad" } }),
    });
    renderWithClient(<TitleNames />);
    const form = await screen.findByRole("form", { name: "Add a Name" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Printed Name" }), "FINANCE: TAX");
    await userEvent.click(within(form).getByRole("combobox", { name: "Office" }));
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("School Education"));
    await userEvent.click(within(form).getByRole("button", { name: "Add Name" }));
    expect(await screen.findByText(/Use capital letters, digits, spaces/)).toBeInTheDocument();
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ phrase: "FINANCE: TAX", office_code: "EDU" }));
  });

  it("says so when every phrase is mapped", async () => {
    routes({ "GET /admin/title-names/unmapped": { items: [], total: 0 } });
    renderWithClient(<TitleNames />);
    expect(await screen.findByText("Every name read from cause titles is mapped.")).toBeInTheDocument();
  });
});

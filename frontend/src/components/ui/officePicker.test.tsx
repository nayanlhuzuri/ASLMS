import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { OfficeChoice } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, renderWithClient } from "@/test/render";

import { OfficePicker } from "./OfficePicker";

function office(code: string, name: string, depth: number, parent: string | null, ancestors: string[], extra: Partial<OfficeChoice> = {}): OfficeChoice {
  return {
    code,
    name,
    kind: depth === 0 ? "state" : depth === 1 ? "department" : "directorate",
    tier: depth === 0 ? "state" : depth === 1 ? "department" : "directorate",
    depth,
    parent_code: parent,
    ancestors,
    is_active: true,
    ...extra,
  };
}

const GOA = office("GOA", "Government of Assam", 0, null, []);
const EDU = office("EDU", "Education", 1, "GOA", ["Government of Assam"]);
const DSE = office("EDU-DSE", "Secondary Education", 2, "EDU", ["Government of Assam", "Education"]);
const HEALTH = office("HEALTH", "Health", 1, "GOA", ["Government of Assam"]);
const OLD = office("EDU-OLD", "Old Cell", 2, "EDU", ["Government of Assam", "Education"], { is_active: false, kind: "unit" });
const TREE = [GOA, EDU, DSE, OLD, HEALTH];

function Harness(props: { initial?: string | null; subtree?: boolean; options?: OfficeChoice[]; purpose?: "users" | "audit"; onValue?: (v: string | null) => void }) {
  const [value, setValue] = useState<string | null>(props.initial ?? null);
  const [sub, setSub] = useState(true);
  return (
    <>
      <OfficePicker
        label="Office"
        purpose={props.options ? undefined : (props.purpose ?? "users")}
        options={props.options}
        value={value}
        onChange={(v) => {
          setValue(v);
          props.onValue?.(v);
        }}
        subtree={props.subtree ? { value: sub, onChange: setSub } : undefined}
        includeInactive={props.purpose === "audit"}
      />
      <output data-testid="value">{value ?? ""}</output>
    </>
  );
}

beforeEach(() => resetNav("/admin/users"));

function routes(items = TREE) {
  return browserApi({ "GET /admin/offices/choices": (call: { path: string }) => ({ purpose: new URL(call.path, "http://x").searchParams.get("purpose"), items }) });
}

describe("the Office Picker (design portal-ui-polish-2, decision 28)", () => {
  it("lists the tree indented by depth with greyed codes and the foot line; the purpose is in the query", async () => {
    const api = routes();
    renderWithClient(<Harness />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.click(box);
    const list = await screen.findByRole("listbox", { name: "Offices" });
    const options = within(list).getAllByRole("option");
    // inactive offices are left out unless the purpose allows them
    expect(options.map((o) => o.textContent)).toEqual(["Government of AssamGOA", "EducationEDU", "Secondary EducationEDU-DSE", "HealthHEALTH"]);
    expect(options[2]!.style.getPropertyValue("--depth")).toBe("2");
    expect(options[1]!.style.getPropertyValue("--depth")).toBe("1");
    expect(screen.getByText("Only offices you can see or act on.")).toBeInTheDocument();
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(box).toHaveAttribute("aria-controls", list.id);
    await waitFor(() => expect(api.calls.some((c) => c.path === "/admin/offices/choices?purpose=users")).toBe(true));
  });

  it("filters by name and by code, shows the path under a match, and says when nothing matches", async () => {
    routes();
    renderWithClient(<Harness />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.type(box, "second");
    let options = within(await screen.findByRole("listbox")).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("Government of Assam › Education");
    expect(options[0]!.querySelector("mark")).toHaveTextContent("Second");
    await userEvent.clear(box);
    await userEvent.type(box, "health");
    options = within(screen.getByRole("listbox")).getAllByRole("option");
    expect(options.map((o) => o.querySelector("[class*='code']")?.textContent)).toEqual(["HEALTH"]);
    await userEvent.clear(box);
    await userEvent.type(box, "edu-d");
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    await userEvent.clear(box);
    await userEvent.type(box, "zzz");
    expect(within(screen.getByRole("listbox")).queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("No office matches")).toBeInTheDocument();
  });

  it("keys: Down opens and moves, Up, Home, End, Enter chooses, Escape closes keeping the value, Tab closes", async () => {
    routes();
    renderWithClient(<Harness initial="EDU" />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await waitFor(() => expect(box).toHaveValue("Education"));
    box.focus();
    await userEvent.keyboard("{ArrowDown}");
    const list = await screen.findByRole("listbox");
    const activeText = () => document.getElementById(box.getAttribute("aria-activedescendant") ?? "")?.textContent;
    // opens on the chosen office
    expect(activeText()).toBe("EducationEDU");
    await userEvent.keyboard("{ArrowDown}");
    expect(activeText()).toBe("Secondary EducationEDU-DSE");
    await userEvent.keyboard("{ArrowUp}");
    expect(activeText()).toBe("EducationEDU");
    await userEvent.keyboard("{End}");
    expect(activeText()).toBe("HealthHEALTH");
    await userEvent.keyboard("{Home}");
    expect(activeText()).toBe("Government of AssamGOA");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("value")).toHaveTextContent("EDU-DSE");
    expect(list).not.toBeInTheDocument();
    await userEvent.keyboard("{ArrowDown}");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("value")).toHaveTextContent("EDU-DSE");
    expect(box).toHaveValue("Secondary Education");
    await userEvent.keyboard("{ArrowDown}");
    await screen.findByRole("listbox");
    await userEvent.tab();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("a click chooses; the clear button empties it; Include Sub-offices shows + sub for an office with children", async () => {
    routes();
    renderWithClient(<Harness subtree />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.click(box);
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Education"));
    expect(screen.getByTestId("value")).toHaveTextContent("EDU");
    expect(screen.getByText("+ sub")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Include Sub-offices"));
    expect(screen.queryByText("+ sub")).toBeNull();
    await userEvent.click(screen.getByLabelText("Include Sub-offices"));
    // an office without children shows no marker
    await userEvent.click(box);
    await userEvent.click(within(await screen.findByRole("listbox")).getByText("Health"));
    expect(screen.queryByText("+ sub")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Clear office" }));
    expect(screen.getByTestId("value")).toHaveTextContent("");
    expect(box).toHaveValue("");
  });

  it("uses the page's options without a call, and marks inactive offices where the purpose allows them", async () => {
    const api = browserApi({});
    renderWithClient(<Harness options={[EDU, HEALTH]} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Office" }));
    const options = within(await screen.findByRole("listbox")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["EducationEDU", "HealthHEALTH"]);
    // indented from the smallest depth given
    expect(options[0]!.style.getPropertyValue("--depth")).toBe("0");
    expect(api.calls).toHaveLength(0);
  });

  it("the audit purpose lists inactive offices with the Inactive badge", async () => {
    routes();
    renderWithClient(<Harness purpose="audit" />);
    await userEvent.click(await screen.findByRole("combobox", { name: "Office" }));
    const old = within(await screen.findByRole("listbox")).getByText("Old Cell").closest("li")!;
    expect(within(old).getByText("Inactive")).toBeInTheDocument();
  });
});

/** The picker's visually hidden status (the harness's `<output>` is a status too). */
const statusSpan = () => document.querySelector<HTMLElement>("span[role='status']")!;

describe("a failed choices load (design office-head-picker-followups, decision 6)", () => {
  it('a failed choices load shows the error note and Try Again, not "No office matches"', async () => {
    let fail = true;
    const api = browserApi({
      "GET /admin/offices/choices": (call: { path: string }) =>
        fail ? new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "content-type": "application/json" } }) : { purpose: new URL(call.path, "http://x").searchParams.get("purpose"), items: TREE },
    });
    renderWithClient(<Harness />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.click(box);
    const list = await screen.findByRole("listbox", { name: "Offices" });
    await waitFor(() => expect(within(list).getByText("The offices could not be loaded.")).toBeInTheDocument());
    expect(screen.queryByText("No office matches")).toBeNull();
    expect(statusSpan()).toHaveTextContent("The offices could not be loaded.");
    const retry = screen.getByRole("button", { name: "Try Again" });
    expect(list.contains(retry)).toBe(false);
    fail = false;
    await userEvent.click(retry);
    await waitFor(() => expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(4));
    expect(api.calls.filter((c) => c.path.startsWith("/admin/offices/choices"))).toHaveLength(2);
    expect(box).toHaveFocus();
  });

  it("a 403 shows the error note with no Try Again; Enter does not ask again", async () => {
    const api = browserApi({
      "GET /admin/offices/choices": () => new Response(JSON.stringify({ detail: { code: "forbidden", message: "no" } }), { status: 403, headers: { "content-type": "application/json" } }),
    });
    renderWithClient(<Harness />);
    const box = await screen.findByRole("combobox", { name: "Office" });
    await userEvent.click(box);
    await within(await screen.findByRole("listbox")).findByText("The offices could not be loaded.");
    expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull();
    await userEvent.keyboard("{Enter}");
    expect(api.calls.filter((c) => c.path.startsWith("/admin/offices/choices"))).toHaveLength(1);
  });
});

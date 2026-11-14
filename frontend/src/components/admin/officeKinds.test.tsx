/**
 * The new office kinds and No Head Yet in Offices (design offices-import, "Tests" and decisions 5 and 23): the Kind
 * options follow the chosen parent, the chosen kind's description is the field hint, and a department with no head
 * shows the No Head Yet badge in the tree and on its page with the line naming the Head Change request.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { OfficeDetail, OfficeNode, Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, labels, makeMe, renderWithClient } from "@/test/render";

import { kindsForParent, NewOfficeForm, OfficeDetailView, OfficesTree } from "./Offices";

const SUPER_FNS: Permission[] = ["users.view", "users.create", "offices.manage", "admin.tickets", "admin.designations"];

const SUPER = makeMe(SUPER_FNS, "super_admin", {
  memberships: [
    {
      id: "m-root",
      office: { code: "GOA", name: "Government of Assam", kind: "state" },
      department_code: null,
      designation: null,
      role: "super_admin",
      is_primary: true,
      is_active: true,
      functions: SUPER_FNS,
    },
  ],
});

const CHOICES = {
  items: [
    { code: "GOA", name: "Government of Assam", kind: "state", tier: "state", depth: 0, parent_code: null, ancestors: [], is_active: true },
    { code: "EDU", name: "Education", kind: "department", tier: "department", depth: 1, parent_code: "GOA", ancestors: ["Government of Assam"], is_active: true },
    {
      code: "EDU-BRD",
      name: "Education Board",
      kind: "board_corporation",
      tier: "directorate",
      depth: 2,
      parent_code: "EDU",
      ancestors: ["Government of Assam", "Education"],
      is_active: true,
    },
  ],
};

function node(code: string, name: string, kind: string, extra: Partial<OfficeNode> = {}): OfficeNode {
  return {
    id: `o-${code}`,
    code,
    name,
    kind: kind as OfficeNode["kind"],
    path: code,
    is_active: true,
    tier: "department",
    depth: 1,
    users_active: 0,
    no_head: false,
    children: [],
    ...extra,
  };
}

function detail(code: string, extra: Partial<OfficeDetail> = {}): OfficeDetail {
  return {
    id: `o-${code}`,
    code,
    name: "Tourism",
    kind: "department",
    path: `GOA/${code}`,
    is_active: true,
    tier: "department",
    depth: 1,
    parent_code: "GOA",
    notes: null,
    deactivated_at: null,
    valid_from: "2026-11-14",
    valid_to: null,
    created_at: "2026-11-14T00:00:00Z",
    updated_at: "2026-11-14T00:00:00Z",
    counts: { children: 0, users: 1, ownership: 0, custody: 0 },
    no_head: false,
    ...extra,
  };
}

function routes(extra: Record<string, unknown> = {}) {
  return browserApi({
    "GET /me": SUPER,
    "GET /reference/labels": labels(["dept_officer", "directorate_user"]),
    "GET /admin/designations": [],
    "GET /admin/offices/choices": (call: { path: string }) => ({ purpose: new URL(call.path, "http://x").searchParams.get("purpose"), ...CHOICES }),
    "GET /admin/users": json(200, [], { "x-total-count": "0" }),
    ...extra,
  });
}

async function chooseParent(name: string) {
  const box = screen.getByRole("combobox", { name: "Parent Office" });
  await userEvent.type(box, name);
  // "Education" must not pick "Education Board": of the options starting with the name, the shortest
  const options = (await screen.findAllByRole("option")).filter((o) => (o.textContent ?? "").trim().startsWith(name));
  const exact = options.sort((x, y) => (x.textContent ?? "").length - (y.textContent ?? "").length)[0];
  await userEvent.click(exact!);
}

function kindOptions(): string[] {
  return within(screen.getByLabelText("Kind"))
    .getAllByRole("option")
    .map((o) => (o as HTMLOptionElement).value)
    .filter(Boolean);
}

beforeEach(() => {
  resetNav("/admin/offices/new");
  window.sessionStorage.clear();
});

describe("kinds for a parent", () => {
  it("offers only the kinds the parent accepts, and every kind but the State with no parent", () => {
    const kinds = labels().office_kinds;
    expect(kindsForParent(kinds, "department").map((k) => k.code)).toEqual(["directorate", "board_corporation", "institution", "unit"]);
    expect(kindsForParent(kinds, "state").map((k) => k.code)).toEqual(["central", "department"]);
    expect(kindsForParent(kinds, "board_corporation").map((k) => k.code)).toEqual(["unit"]);
    expect(kindsForParent(kinds, undefined).map((k) => k.code)).not.toContain("state");
  });
});

describe("New Office (decision 5)", () => {
  it("the Kind options follow the parent and the kind's description is the hint", async () => {
    routes();
    renderWithClient(<NewOfficeForm />);
    await waitFor(() => expect(kindOptions().length).toBeGreaterThan(1));
    expect(kindOptions()).not.toContain("state");
    await chooseParent("Education");
    await waitFor(() => expect(kindOptions()).toEqual(["directorate", "board_corporation", "institution", "unit"]));
    expect(kindOptions()).not.toContain("department");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "board_corporation");
    expect(
      screen.getByText("State public sector companies, corporations, boards and federations that act in their own name."),
    ).toBeInTheDocument();
    // a parent that does not accept the chosen kind clears it
    await userEvent.clear(screen.getByRole("combobox", { name: "Parent Office" }));
    await chooseParent("Education Board");
    await waitFor(() => expect(kindOptions()).toEqual(["unit"]));
    expect(screen.getByLabelText("Kind")).toHaveValue("");
  });

  it("under the State root only the Department-tier kinds are offered", async () => {
    resetNav("/admin/offices/new", "parent=GOA");
    routes();
    renderWithClient(<NewOfficeForm />);
    await waitFor(() => expect(kindOptions()).toEqual(["central", "department"]));
  });
});

describe("No Head Yet (decision 23)", () => {
  it("the tree shows the badge on a department with no head only", async () => {
    routes({
      "GET /admin/offices/tree": [
        node("GOA", "Government of Assam", "state", {
          tier: "state",
          depth: 0,
          children: [node("TOURISM", "Tourism", "department", { no_head: true }), node("EDU", "Education", "department")],
        }),
      ],
    });
    renderWithClient(<OfficesTree />);
    const tourism = (await screen.findByRole("link", { name: "Tourism" })).closest("li")!;
    expect(within(tourism).getByText("No Head Yet")).toBeInTheDocument();
    const edu = screen.getByRole("link", { name: "Education" }).closest("li")!;
    expect(within(edu).queryByText("No Head Yet")).toBeNull();
  });

  it("the office page shows the badge and the line to the Head Change request", async () => {
    resetNav("/admin/offices/TOURISM");
    routes({
      "GET /admin/offices/TOURISM": detail("TOURISM", { no_head: true }),
      "GET /admin/offices/TOURISM/admins": [],
    });
    renderWithClient(<OfficeDetailView code="TOURISM" />);
    expect(await screen.findByText("No Head Yet")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Name the head through a Head Change request" });
    expect(link).toHaveAttribute("href", "/admin/tickets/new?department=TOURISM&operation=set");
  });

  it("a department with a head shows neither", async () => {
    resetNav("/admin/offices/EDU");
    routes({ "GET /admin/offices/EDU": detail("EDU", { name: "Education" }), "GET /admin/offices/EDU/admins": [] });
    renderWithClient(<OfficeDetailView code="EDU" />);
    expect(await screen.findByRole("heading", { name: /Education/ })).toBeInTheDocument();
    expect(screen.queryByText("No Head Yet")).toBeNull();
    expect(screen.queryByRole("link", { name: "Name the head through a Head Change request" })).toBeNull();
  });
});
